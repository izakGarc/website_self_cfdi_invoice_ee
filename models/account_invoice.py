# -*- coding: utf-8 -*-

from odoo import models, fields, SUPERUSER_ID


class AccountInvoice(models.Model):
    _inherit = 'account.move'

    self_invoice = fields.Boolean('Self invoice', default=False)

    def force_invoice_send(self):
        """Enviar la factura por correo usando el sistema de envío de Odoo 19."""
        for inv in self:
            try:
                self.env['account.move.send'].sudo()._generate_and_send_invoices(
                    inv,
                    sending_methods=['email'],
                )
            except Exception:
                # Fallback: intentar con la plantilla de correo directamente
                template = self.env.ref(
                    'account.email_template_edi_invoice', raise_if_not_found=False
                )
                if template:
                    template.sudo().send_mail(inv.id, force_send=True)
        return True

    def _l10n_mx_edi_cfdi_invoice_document_sent(self, cfdi_filename, cfdi_str):
        """Hook post-timbrado: si la factura es self_invoice, enviar correo."""
        document = super()._l10n_mx_edi_cfdi_invoice_document_sent(cfdi_filename, cfdi_str)
        if self.self_invoice:
            self.force_invoice_send()
            self.self_invoice = False
        return document
