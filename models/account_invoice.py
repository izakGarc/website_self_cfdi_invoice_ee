# -*- coding: utf-8 -*-

from odoo import models, api, fields, SUPERUSER_ID
from itertools import groupby

class AccountInvoice(models.Model):
    _inherit = 'account.move'

    self_invoice = fields.Boolean('Self invoice', default=False)

    def force_invoice_send(self):
        for inv in self:
            email_act = inv.action_invoice_sent()
            if email_act and email_act.get('context'):
                email_ctx = email_act['context']
                email_ctx.update(default_email_from=inv.company_id.email)
                inv.with_context(email_ctx).with_user(SUPERUSER_ID).message_post_with_template(email_ctx.get('default_template_id'))
        return True

    def _l10n_mx_edi_post_sign_process(self, xml_signed, code=None, msg=None):
        res = super(AccountInvoice, self)._l10n_mx_edi_post_sign_process(xml_signed, code=code, msg=msg)
        if self.self_invoice:
            self.force_invoice_send()
            self.self_invoice = False
        return res

    def invoice_validate(self):
        res = super(AccountInvoice, self).invoice_validate()
        # attachment_obj = self.env['ir.attachment']
        for invoice in self:
            self.env.cr.execute(
                "delete from ir_attachment where name like 'Factura_%s' and res_id = %s and res_model='account.move';" % (
                '%', invoice.id,))
        return res

    def _l10n_mx_edi_call_service(self, service_type):
        '''Call the right method according to the pac_name, it's info returned by the '_l10n_mx_edi_%s_info' % pac_name'
        method and the service_type passed as parameter.
        :param service_type: sign or cancel
        '''
        # Regroup the invoices by company (= by pac)
        comp_x_records = groupby(self, lambda r: r.company_id)
        for company_id, records in comp_x_records:
            pac_name = company_id.l10n_mx_edi_pac
            if not pac_name:
                continue
            # Get the informations about the pac
            pac_info_func = '_l10n_mx_edi_%s_info' % pac_name
            service_func = '_l10n_mx_edi_%s_%s' % (pac_name, service_type)
            pac_info = getattr(self, pac_info_func)(company_id, service_type)
            # Call the service with invoices one by one or all together according to the 'multi' value.
            multi = pac_info.pop('multi', False)
            if multi:
                # rebuild the recordset
                records = self.env['account.move'].search(
                    [('id', 'in', self.ids), ('company_id', '=', company_id.id)])
                getattr(records, service_func)(pac_info)
            else:
                for record in records:
                    getattr(record, service_func)(pac_info)
