# -*- coding: utf-8 -*-

from odoo import models, fields, api, SUPERUSER_ID
import base64
import time
import logging
_logger = logging.getLogger(__name__)
from datetime import date, timedelta
import datetime

class website_self_invoice_web(models.Model):
    _name = 'website.self.invoice.web'
    _description = 'Portal de Autofacturacion Integrado a Odoo'
    _rec_name = 'order_number'
    _order = 'create_date desc'

    datas_fname = fields.Char('File Name', size=256)
    file = fields.Binary('Layout')
    download_file = fields.Boolean('Descargar Archivo')
    cadena_decoding = fields.Text('Binario sin encoding')
    type = fields.Selection([('csv', 'CSV'), ('xlsx', 'Excel')], 'Tipo Exportacion',
                            required=False, )
    rfc_partner = fields.Char('RFC', size=15, default='XAXX010101000')
    order_number = fields.Char('Folio Pedido de Venta', size=128)
    monto_total = fields.Float('Monto total')
    mail_to = fields.Char('Correo Electronico', size=256)
    ticket_pos = fields.Boolean('Ticket', default=False)
    state = fields.Selection([('draft', 'Borrador'), ('error', 'Error'), ('done', 'Relizado')])

    attachment_ids = fields.One2many('website.self.invoice.web.attach', 'website_auto_id', 'Adjuntos del Portal')
    partner_id = fields.Many2one("res.partner", "Partner")
    l10n_mx_edi_usage = fields.Selection([
        ('G01', 'Acquisition of merchandise'),
        ('G02', 'Returns, discounts or bonuses'),
        ('G03', 'General expenses'),
        ('I01', 'Constructions'),
        ('I02', 'Office furniture and equipment investment'),
        ('I03', 'Transportation equipment'),
        ('I04', 'Computer equipment and accessories'),
        ('I05', 'Dices, dies, molds, matrices and tooling'),
        ('I06', 'Telephone communications'),
        ('I07', 'Satellite communications'),
        ('I08', 'Other machinery and equipment'),
        ('D01', 'Medical, dental and hospital expenses.'),
        ('D02', 'Medical expenses for disability'),
        ('D03', 'Funeral expenses'),
        ('D04', 'Donations'),
        ('D05', 'Real interest effectively paid for mortgage loans (room house)'),
        ('D06', 'Voluntary contributions to SAR'),
        ('D07', 'Medical insurance premiums'),
        ('D08', 'Mandatory School Transportation Expenses'),
        ('D09', 'Deposits in savings accounts, premiums based on pension plans.'),
        ('D10', 'Payments for educational services (Colegiatura)'),
        ('S01', 'Sin efectos fiscales'),
    ], 'Usage', default='S01',
        help='Used in CFDI 4.0 to express the key to the usage that will '
             'gives the receiver to this invoice. This value is defined by the '
             'customer. \nNote: It is not cause for cancellation if the key set is '
             'not the usage that will give the receiver of the document.')
    error_message = fields.Text('Mensaje de Error')
    partner_id = fields.Many2one('res.partner', string="Cliente interno")
    uso_cfdi = fields.Char('Uso de CFDI')
    l10n_mx_edi_payment_method_id = fields.Many2one('l10n_mx_edi.payment.method', string='Forma de Pago')
    forma_de_pago_cfdi = fields.Char('Forma de Pago CFDI')

    _defaults = {
        'download_file': False,
        'type': 'csv',
        'state': 'draft',
    }

    def website_form_input_filter(self, request, values):
        values['medium_id'] = (
                values.get('medium_id') or
                self.default_get(['medium_id']).get('medium_id') or
                self.sudo().env['ir.model.data'].xmlid_to_res_id('utm.utm_medium_website')
        )
        return values

    def write(self, values):
        result = super(website_self_invoice_web, self).write(values)
        return result

    @api.model
    def create(self, values):
        result = super(website_self_invoice_web, self).create(values)
        ### Validacion de Campos Obligatorios ###
        if not result.rfc_partner or not result.order_number or not result.monto_total:  # or not result.mail_to:
            result.write({
                'error_message': 'Los campos Marcados con un ( * ) son Obligatorios.',
                'state': 'error',
            })
            return result
        if not result.partner_id:
            self.env.cr.execute("""
                select id from res_partner where UPPER(vat) like %s;
                """, ('%' + result.rfc_partner.upper() + '%',))
            cr_res = self.env.cr.fetchall()
            order_id = False

            try:
                partner_id = cr_res[0][0]
            except:
                result.write({
                    'error_message': 'El RFC %s no existe en la Base de Datos.' % result.rfc_partner,
                    'state': 'error',
                })
                return result
        else:
            partner_id = result.partner_id.id
        ##### Retornamos  la Factura en caso que exista ####
        #self.env.cr.execute(f"select id from sale_order where UPPER(name) like '%{result.order_number.upper()}' and round(amount_total,2)={result.monto_total or 0};")
        self.env.cr.execute("""
                select id from sale_order where UPPER(name) like '%s' and round(amount_total,2)=%s;
                """ % ('%'+result.order_number.upper(), result.monto_total or 0))
        cr_res = self.env.cr.fetchall()
        ticket_pos = False
        try:
            order_id = cr_res[0][0]
            ticket_pos = False
        except:
            enable_pos = False
            module = self.env['ir.module.module'].sudo().search([('name','=','point_of_sale')])
            if module and module.state == 'installed':
                enable_pos = True
            if enable_pos:
                self.env.cr.execute("""
                    select id from pos_order where pos_reference like %s and round(amount_total,2)=%s;
                    """, ('%'+result.order_number,result.monto_total or 0))
                cr_res = self.env.cr.fetchall()
                try:
                    order_id = cr_res[0][0]
                    ticket_pos = True
                except:
                    result.write({
                        'error_message':'El Ticket %s no existe en la Base de Datos.' % result.order_number,
                        'state': 'error',
                    })
                    return result
            else:
                result.write({
                        'error_message':'El Pedido %s no existe en la Base de Datos.' % result.order_number,
                        'state': 'error',
                })
                return result

        tryagain = False
        if order_id and ticket_pos == False:
            order_obj = self.env['sale.order'].sudo()
            order_br = order_obj.browse(order_id)
            # Forzar compañía correcta para todo el proceso EDI
            self = self.with_company(order_br.company_id.id)
            result.order_number = order_br.name

            if order_br.state in ('draft', 'sent'):
                result.write({
                    'error_message': 'El Pedido %s se encuentra en espera de ser procesado, por favor comuniquese con la compañia.' % order_br.name,
                    'state': 'error',
                })
                return result

            #if order_br.invoice_status != 'no':
            if order_br.invoice_status in ['no', 'to invoice']:
                invoice_return = None
                if order_br.invoice_status == 'invoiced':
                    invoice_return = order_br.invoice_ids.filtered(lambda r: r.state != 'cancel')
                    if invoice_return and invoice_return[0].edi_state == 'sent':
                        result.write({
                            'error_message': 'El Pedido %s ya fue Facturado.' % result.order_number,
                            'state': 'error',
                        })
                        return result
                else:
                    if not result.l10n_mx_edi_usage:
                        result.write({
                           'error_message':'No tiene asignado un uso de CFDI en el cliente. Favor de asignar uno antes de facturar el pedido %s.' % order_br.name,
                           'state': 'error',
                        })
                        return result
                    # Asignar forma de pago del portal al pedido antes de validar
                    if result.l10n_mx_edi_payment_method_id and not order_br.l10n_mx_edi_payment_method_id:
                        order_br.write({'l10n_mx_edi_payment_method_id': result.l10n_mx_edi_payment_method_id.id})

                    if not order_br.l10n_mx_edi_payment_method_id:
                        result.write({
                            'error_message': 'El pedido %s no pudo facturarse ya que no cuenta con una forma de pago asignada, comuniquese con la compañia.' % order_br.name,
                            'state': 'error',
                        })
                        return result
                    invoice_return = order_br.with_company(order_br.company_id.id)._create_invoices()
                invoice_br = self.env['account.move'].sudo().search([('id', '=', invoice_return.id)])
                vals = {}
                if hasattr(invoice_br, 'factura_cfdi'):
                    vals.update({'factura_cfdi': True, })
                vals.update({'l10n_mx_edi_usage': result.l10n_mx_edi_usage})
                vals.update({'l10n_mx_edi_payment_policy': 'PUE'})
                if invoice_br.partner_id.id != partner_id:
                    vals.update({'partner_id': partner_id})
                if invoice_br.company_id != order_br.company_id:
                    vals.update({'company_id': order_br.company_id})

                #insertado por pcsystems
                if order_br.l10n_mx_edi_payment_method_id != result.l10n_mx_edi_payment_method_id:
                    order_br.write({'l10n_mx_edi_payment_method_id': result.l10n_mx_edi_payment_method_id.id})         
                #termina inserción
                
                if order_br.l10n_mx_edi_payment_method_id:
                    vals.update({'l10n_mx_edi_payment_method_id': order_br.l10n_mx_edi_payment_method_id.id})

                invoice_br.write(vals)
                _logger.info('Partner PEDIDO: %s | ZIP: %s | VAT: %s',
                    order_br.partner_id.name,
                    order_br.partner_id.zip,
                    order_br.partner_id.vat)
                _logger.info('Partner FACTURA: %s | ZIP: %s | VAT: %s',
                    invoice_br.partner_id.name,
                    invoice_br.partner_id.zip,
                    invoice_br.partner_id.vat)
                if invoice_br.state == 'draft':
                    invoice_br.with_company(invoice_br.company_id.id).sudo().action_post()
                    import time as time_module
                    time_module.sleep(1)
                    invoice_br.invalidate_recordset()
                    edi_docs = invoice_br.edi_document_ids.filtered(lambda d: d.state in ('to_send', 'to_cancel'))
                    if edi_docs:
                        edi_docs.sudo().with_company(invoice_br.company_id.id)._process_documents_web_services(with_commit=False)
                    time_module.sleep(3)
                    invoice_br.invalidate_recordset()

                if invoice_br.edi_state == 'to_send':
                    invoice_br.sudo().action_retry_edi_documents_error()
                    for _ in range(10):
                        invoice_br.invalidate_recordset()
                        if invoice_br.edi_state in ('sent', 'to_cancel'):
                            break
                        if invoice_br.edi_document_ids.filtered(lambda d: d.error):
                            break
                        time_module.sleep(2)

                if invoice_br.edi_state != 'sent':
                    edi_doc = invoice_br.edi_document_ids.filtered(lambda d: d.error)
                    edi_error = edi_doc[0].error if edi_doc else ''
                    
                    # Rollback: cancelar y eliminar la factura
                    try:
                        if invoice_br.state == 'posted':
                            invoice_br.sudo().button_cancel()
                        if invoice_br.state in ('draft', 'cancel'):
                            invoice_br.sudo().unlink()
                        order_br.sudo().write({'invoice_status': 'to invoice'})
                    except Exception as e:
                        _logger.warning('No se pudo hacer rollback de factura: %s', str(e))
                    
                    user_errors = ['rfc', 'código postal', 'cp', 'regimen', 'régimen', 'uso', 'cfdi', 
                                    'receptor', 'domicilio', 'fiscal', 'lugarexpedicion', 'domiciliofiscal']
                    is_user_error = any(kw in edi_error.lower() for kw in user_errors)
                    msg = 'El Pedido %s no se pudo timbrar.' % result.order_number
                    import re
                    # Limpiar HTML del mensaje del PAC
                    edi_error_clean = re.sub(r'<[^>]+>', ' ', edi_error).strip()
                    edi_error_clean = re.sub(r'\s+', ' ', edi_error_clean)
                    if edi_error:
                        msg += ' Detalle del SAT: %s' % edi_error_clean
                    if not is_user_error:
                        msg += ' Favor de contactar a soporte@loomber.com'
                    result.write({'error_message': msg, 'state': 'error'})
                    return result

                result.write({'attachment_ids': []})
                result.write({'state': 'done'})
                invoice_br.force_invoice_send()
            else:
                result.write({
                    'error_message': 'El Pedido %s ya fue Facturado.' % result.order_number,
                    'state': 'error',
                })
                return result
        if order_id and ticket_pos == True:
            invoice_obj = self.env['account.move'].sudo()
            pos_order_obj = self.env['pos.order'].sudo()
            pos_br = pos_order_obj.browse(order_id)
            # Forzar compañía correcta para todo el proceso EDI
            self = self.with_company(pos_br.company_id.id)
            pos_br.write({'partner_id': partner_id})
            if pos_br.partner_id:
                if pos_br.partner_id.id != partner_id:
                    result.write({
                        'error_message': 'El RFC %s no pertenece al Pedido de Venta %s.' % (result.rfc_partner, result.order_number,),
                        'state': 'error',
                    })
                    return result
            if pos_br.state != 'cancel' and pos_br.state != 'draft':
                if not pos_br.payment_ids[0].payment_method_id.forma_pago:
                    result.write({
                        'error_message': 'Favor de contactar al departamento de facturación ya que falta configurar el método de pago.',
                        'state': 'error',
                    })
                    return result
                if not result.l10n_mx_edi_usage:
                    result.write({
                        'error_message':'No tiene asignado un uso de CFDI en el cliente. Favor de asignar uno antes de facturar el pedido %s.' % order_br.name,
                        'state': 'error',
                    })
                    return result
                invoice_id = None
                if pos_br.state == 'invoiced':
                   invoice_br = invoice_obj.search([('invoice_origin', '=', pos_br.name), ('state', '!=', 'cancel')], limit=1)
                   tryagain = True

                   if invoice_br and invoice_br[0].edi_state == 'sent':
                       result.write({
                           'error_message': 'El Pedido %s ya fue Facturado.' % result.order_number,
                           'state': 'error',
                       })
                       return result
                else:
                    moves = self.env['account.move']

                    vals = {
                        'payment_reference': pos_br.name,
                        'invoice_origin': pos_br.name,
                        'journal_id': pos_br.session_id.config_id.invoice_journal_id.id,
                        'move_type': 'out_invoice' if pos_br.amount_total >= 0 else 'out_refund',
                        'ref': pos_br.name,
                        'partner_id': pos_br.partner_id.id,
                        'narration': pos_br.note or '',
                        # considering partner's sale pricelist's currency
                        'currency_id': pos_br.pricelist_id.currency_id.id,
                        'invoice_user_id': pos_br.user_id.id,
                        'invoice_date': (datetime.datetime.now() - timedelta(hours=6)).date(),
                        'fiscal_position_id': pos_br.fiscal_position_id.id,
                        'invoice_line_ids': [(0, None, pos_br._prepare_invoice_line(line)) for line in pos_br.lines],
                    }

                    new_move = self.env['account.move'].sudo().with_company(pos_br.company_id).with_context(
                        default_move_type='out_invoice').create(vals)
                    # message = _("This invoice has been created from the point of sale session: <a href=# data-oe-model=pos.order data-oe-id=%d>%s</a>") % (self.id, self.name)
                    # new_move.message_post(body=message)

                    pos_br.write({'account_move': new_move.id, 'state': 'invoiced'})
                    invoice_id = new_move and new_move.ids[0] or False
                    invoice_br = invoice_obj.browse(invoice_id)

                vals = {}
                if hasattr(invoice_obj, 'factura_cfdi'):
                    vals.update({'factura_cfdi': True, })
                vals.update({'l10n_mx_edi_usage': result.l10n_mx_edi_usage})
                vals.update({'l10n_mx_edi_payment_policy': 'PUE'})
                if invoice_br.partner_id.id != partner_id:
                    vals.update({'partner_id': partner_id})
                if pos_br.payment_ids:
                    payment_method_code = pos_br.payment_ids[0].payment_method_id.forma_pago
                    l10n_mx_edi_payment_method = self.env['l10n_mx_edi.payment.method'].sudo().search(
                        [('code', '=', payment_method_code)])
                    vals.update({'l10n_mx_edi_payment_method_id': l10n_mx_edi_payment_method.id})
                if not invoice_br.invoice_payment_term_id:
                    payment_term_immediate = self.env.ref('account.account_payment_term_immediate', raise_if_not_found=False)
                    vals.update({'invoice_payment_term_id': payment_term_immediate.id})
                invoice_br.write(vals)
                
                _logger.info('Partner PEDIDO: %s | ZIP: %s | VAT: %s',
                    order_br.partner_id.name,
                    order_br.partner_id.zip,
                    order_br.partner_id.vat)
                _logger.info('Partner FACTURA: %s | ZIP: %s | VAT: %s',
                    invoice_br.partner_id.name,
                    invoice_br.partner_id.zip,
                    invoice_br.partner_id.vat)
                if invoice_br.state == 'draft':
                    invoice_br.with_company(invoice_br.company_id.id).sudo().action_post()
                    import time as time_module
                    time_module.sleep(1)
                    invoice_br.invalidate_recordset()
                    edi_docs = invoice_br.edi_document_ids.filtered(lambda d: d.state in ('to_send', 'to_cancel'))
                    if edi_docs:
                        edi_docs.sudo().with_company(invoice_br.company_id.id)._process_documents_web_services(with_commit=False)
                    time_module.sleep(3)
                    invoice_br.invalidate_recordset()
                #_logger.info('uuid %s partner %s nombre %s uso_cfdi %s', invoice_br.l10n_mx_edi_cfdi_uuid,
                #             invoice_br.partner_id.name, invoice_br.name, invoice_br.l10n_mx_edi_usage)

                if invoice_br.edi_state != 'sent':
                    edi_doc = invoice_br.edi_document_ids.filtered(lambda d: d.error)
                    edi_error = edi_doc[0].error if edi_doc else ''
                    
                    # Rollback: cancelar y eliminar la factura
                    try:
                        if invoice_br.state == 'posted':
                            invoice_br.sudo().button_cancel()
                        if invoice_br.state in ('draft', 'cancel'):
                            invoice_br.sudo().unlink()
                        pos_br.sudo().write({'state': 'done', 'account_move': False})
                    except Exception as e:
                        _logger.warning('No se pudo hacer rollback de factura POS: %s', str(e))
                    
                    user_errors = ['rfc', 'código postal', 'cp', 'regimen', 'régimen', 'uso', 'cfdi', 
                                    'receptor', 'domicilio', 'fiscal', 'lugarexpedicion', 'domiciliofiscal']
                    is_user_error = any(kw in edi_error.lower() for kw in user_errors)
                    msg = 'El ticket %s no se pudo timbrar.' % result.order_number
                    import re
                    # Limpiar HTML del mensaje del PAC
                    edi_error_clean = re.sub(r'<[^>]+>', ' ', edi_error).strip()
                    edi_error_clean = re.sub(r'\s+', ' ', edi_error_clean)
                    if edi_error:
                        msg += ' Detalle del SAT: %s' % edi_error_clean
                    if not is_user_error:
                        msg += ' Favor de contactar a soporte@loomber.com'
                    result.write({'error_message': msg, 'state': 'error'})
                    return result

                result.write({'attachment_ids': []})
                result.write({'state': 'done'})
                invoice_br.force_invoice_send()
            else:
                result.write({
                            'error_message':'El Ticket %s no se puede facturar, favor de contactar al departamento de facturación.' % result.order_number,
                            'state': 'error',
                        })
                return result

        return result

class website_self_invoice_web_attach(models.Model):
    _name = 'website.self.invoice.web.attach'
    _description = 'Adjuntos para Portal de Auto Facturacion'

    website_auto_id = fields.Many2one('website.self.invoice.web', 'ID Ref')
    attach_id = fields.Many2one('ir.attachment', 'Adjunto')
    store_fname = fields.Char('File Name', size=256, related="attach_id.store_fname")
    file = fields.Binary('Archivo Binario', related="attach_id.datas")
