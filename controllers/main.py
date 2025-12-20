# -*- coding: utf-8 -*-
from odoo.http import request, route
from datetime import datetime
from odoo import http
from odoo.addons.http_routing.models.ir_http import slug
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.portal.controllers.portal import CustomerPortal

class WebsiteSaleExtend(WebsiteSale):

    def _get_mandatory_billing_fields(self):
        field_list = super(WebsiteSaleExtend, self)._get_mandatory_billing_fields()
        field_list.append('zip')
        return field_list

    def _get_mandatory_shipping_fields(self):
        field_list = super(WebsiteSaleExtend, self)._get_mandatory_shipping_fields()
        field_list.append('zip')
        return field_list
    def values_postprocess(self, order, mode, values, errors, error_msg):
        res = super(WebsiteSaleExtend, self).values_postprocess(order, mode, values, errors, error_msg)
        if values.get('uso_cfdi') and hasattr(order, 'uso_cfdi'):
            order.write({'uso_cfdi': values.get('uso_cfdi')})
            res[0].update({'uso_cfdi': values.get('uso_cfdi')})
        return res


class FacturaCliente(http.Controller):
    
    @http.route('/portal/facturacliente/', auth='public', website=True)
    def index(self, **kw):
        #SE AGREGA MODIFICACIÓN PARA VALIDACIÓN DE HORARIO PARA EVITAR FACTURACIÓN FUERA DE HORARIOS.
        #MODIFICADO POR ELIAS VILLEGAS 02 DE ABRIL DEL 2025.
        hora_actual = datetime.now().hour
        diferencia_horaria = -7
        hora_local = (hora_actual + diferencia_horaria) % 24
        hora_permitida = 9 <= hora_local <=20  
        return http.request.render('website_self_cfdi_invoice_ee.index',
            {
                'fields': ['RFC','Folio',],
                'hora_permitida': hora_permitida,
                'hora_actual': hora_actual,
                'hora_local':hora_local
            })

    @http.route('/portal/facturacliente/rfc',type="http", auth="public", csrf=False, website=True)
    def my_fact_portal_check(self, **kwargs):
        rfc_partner = kwargs.get('rfc_partner') or 'XAXX010101000'
        order_number = kwargs['order_number'] or False
        monto_total = kwargs.get('monto_total',0) or 0.00
        
        partner_obj = http.request.env['res.partner']
        sale_obj =  http.request.env['sale.order']

        partner_obj = partner_obj.sudo()
        #partner_exist = partner_obj.search([('vat', '=', rfc_partner)],limit=1)
        partner_exist = partner_obj.search([('vat', '=', rfc_partner)])

        enable_pos = False
        module = http.request.env['ir.module.module'].sudo().search([('name','=','point_of_sale')])
        if module and module.state == 'installed':
            enable_pos = True
            pos_obj =  http.request.env['pos.order']

        partner_exist = True
        if partner_exist:
            sale_obj = sale_obj.sudo()
            #sale_order_exist = sale_obj.search([('partner_id','in',partner_exist.ids),('name', 'like', order_number),('amount_total','=',float(monto_total.replace(',','')))],limit=1)
            #sale_order_exist = sale_obj.search([('name', 'like', order_number),('amount_total','=',float(monto_total.replace(',','')))],limit=1)
            sale_order_exist = sale_obj.search([('name', 'like', order_number)],limit=1)
            if sale_order_exist:
                order_number = sale_order_exist.name
                monto_total = sale_order_exist.amount_total
                kwargs.update({'monto_total': monto_total})
                return http.request.render('website_self_cfdi_invoice_ee.facturacion',
                                                                            {
                                                                            'partner_name': sale_order_exist.partner_id.name,
                                                                            'cp_post': sale_order_exist.partner_id.zip or False,
                                                                            'correo_electronico': sale_order_exist.partner_id.email or False,
            #                                                                'uso_del_cfdi': sale_order_exist.partner_id.uso_cfdi_id.code or False,
                                                                            'regimen_fiscal': sale_order_exist.partner_id.l10n_mx_edi_fiscal_regime or False,
                                                                            'order_number': order_number,
                                                                            'monto_total': monto_total,
                                                                            })
            elif enable_pos:
                pos_obj = pos_obj.sudo()
                pos_order_exist = pos_obj.search([('pos_reference', '=', order_number),('amount_total','=',float(monto_total.replace(',','')))],limit=1)
                if pos_order_exist:
                    return http.request.render('website_self_cfdi_invoice_ee.facturacion',
                                                                            {
                                                                            'partner_name': partner_exist.name,
                                                                            'cp_post': partner_exist.zip or False,
                                                                            'correo_electronico': partner_exist.email or False,
             #                                                               'uso_del_cfdi': partner_exist.uso_cfdi_id.code or False,
                                                                            'regimen_fiscal': partner_exist.l10n_mx_edi_fiscal_regime or False
                                                                            })
                else:
                    return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', {'errores':['No se encontró el pedido o ticket de venta o el monto no coincide con el pedido.']})
            else:
                return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', {'errores':['No se encontró el pedido de venta. Debe revisar monto, RFC y número del pedido.']})
        else:
            if enable_pos:
                pos_obj = pos_obj.sudo()
                pos_order_exist = pos_obj.search([('pos_reference', '=', order_number),('amount_paid','=',float(monto_total.replace(',','')))],limit=1)
                if pos_order_exist:
                   return http.request.render('website_self_cfdi_invoice_ee.facturacion', {})
                else:
                   return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', {'errores':['No se encontró el pedido. Debe revisar monto y número del pedido.']})
            else:
               return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', {'errores':['No se encontró el pedido de venta. Debe revisar monto, RFC y número del pedido.']})


    @http.route('/portal/facturacliente/results/', type="http", auth="public", csrf=False, website=True)
    def my_fact_portal_insert(self, **kwargs):
        partner = request.env.user.partner_id
        rfc_partner = kwargs.get('rfc_partner') or (partner.vat and partner.vat.replace('MX', '')) or False
        order_number = kwargs.get('order_number') or False
        mail_to = kwargs.get('mail_to', False)
        ticket_pos = kwargs.get('ticket_pos', False)
        monto_total = kwargs.get('monto_total', '0')
        forma_de_pago_cfdi = kwargs.get('forma_de_pago_cfdi', False)
        partner_name = kwargs.get('partner_name', False)
        correo_electronico = kwargs.get('correo_electronico', False)
        cp_post = kwargs.get('cp_post', False)
        regimen_fiscal = kwargs.get('regimen_fiscal', False)
        uso_del_cfdi = kwargs.get('uso_del_cfdi', False)
        
        # VALIDACIÓN TEMPRANA - ANTES DE PROCESAR
        errores = []
        if not rfc_partner:
            errores.append('El RFC es obligatorio.')
        if not order_number:
            errores.append('El Folio de Venta es obligatorio.')
        if not monto_total or monto_total == '0':
            errores.append('El Monto Total es obligatorio.')
        if not correo_electronico:
            errores.append('El Correo electrónico es obligatorio.')
        if not partner_name:
            errores.append('El Nombre es obligatorio.')
        if not regimen_fiscal:
            errores.append('El Régimen Fiscal es obligatorio.')
        if not uso_del_cfdi:
            errores.append('El Uso del CFDI es obligatorio.')
        if not forma_de_pago_cfdi:
            errores.append('La Forma de Pago es obligatoria.')
        
        # Si hay errores, retornar inmediatamente
        if errores:
            return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', {'errores': errores})
        
        # Validar y convertir monto_total de forma segura
        try:
            monto_total_clean = monto_total.replace(',', '').strip()
            monto_total_float = float(monto_total_clean)
            if monto_total_float <= 0:
                return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', 
                                        {'errores': ['El monto total debe ser mayor a 0.']})
        except (ValueError, AttributeError):
            return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', 
                                    {'errores': ['El monto total no es válido. Use solo números (ej: 1234.56)']})
        
        if 'ticket_pos' in kwargs:
            ticket_pos = kwargs.get('ticket_pos') or True
        else:
            ticket_pos = False
        
        auto_invoice_obj = http.request.env['website.self.invoice.web'].sudo()
        partner_obj = http.request.env['res.partner'].sudo()
        partner_exist = partner_obj.search([('vat', '=', rfc_partner.upper())], limit=1)
        partner_vals = {}
        
        if partner_exist:
            if partner_exist.email != correo_electronico:
                if partner_exist.email:
                    partner_vals.update({'email': partner_exist.email + '; ' + correo_electronico})
                else:
                    partner_vals.update({'email': correo_electronico})
            partner_vals.update({'name': partner_name})
            partner_vals.update({'l10n_mx_edi_fiscal_regime': regimen_fiscal})
            partner_vals.update({'zip': cp_post})
            partner_exist.write(partner_vals)
        else:
            partner_vals.update({'name': partner_name})
            partner_vals.update({"vat": rfc_partner.upper()})
            partner_vals.update({'email': correo_electronico})
            partner_vals.update({'l10n_mx_edi_fiscal_regime': regimen_fiscal})
            partner_vals.update({'zip': cp_post})
            partner_vals.update({'country_id': http.request.env['res.country'].search([('code', '=', 'MX')], limit=1).id})
            partner_exist = partner_obj.create(partner_vals)
        
        # Revisar si ya existe una factura previa
        request_preview = auto_invoice_obj.search([
            ('rfc_partner', '=', rfc_partner.upper()), 
            ('order_number', 'like', order_number), 
            ('state', '=', 'done')
        ])
        if request_preview:
            attachment_obj = http.request.env['website.self.invoice.web.attach'].sudo()
            attachments = attachment_obj.search([('website_auto_id', '=', request_preview[0].id)])
            return http.request.render('website_self_cfdi_invoice_ee.html_result_thnks', {
                'attachments': attachments,
            })
        
        # Crear la factura
        auto_invoice_id = auto_invoice_obj.create({
            'rfc_partner': rfc_partner.upper(),
            'order_number': order_number,
            'monto_total': monto_total_float,
            'l10n_mx_edi_usage': uso_del_cfdi,
            'l10n_mx_edi_payment_method_id': int(forma_de_pago_cfdi),
            'ticket_pos': ticket_pos,
            'partner_id': partner_exist.id,
        })
        
        attachment_obj = http.request.env['website.self.invoice.web.attach'].sudo()
        attachments = attachment_obj.search([('website_auto_id', '=', auto_invoice_id.id)])
        
        if auto_invoice_id.error_message:
            return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', 
                                    {'errores': [auto_invoice_id.error_message]})
        
        return http.request.render('website_self_cfdi_invoice_ee.html_result_thnks', {
            'attachments': attachments,
        })

    @http.route('/portal/consulta_factura/', type="http", auth="user", csrf=False, website=True)
    def request_invoice(self, **kwargs):
        if not kwargs:
            return http.request.render('website_self_cfdi_invoice_ee.index',
                                       {
                                           'fields': ['RFC', 'Folio', ],
                                       })
        partner = request.env.user.partner_id.sudo()
        rfc_partner = kwargs['rfc_partner'] or (partner.vat and partner.vat.replace('MX', '')) or False
        order_number = kwargs['order_number'] or False
        monto_total = kwargs.get('monto_total', 0)

        auto_invoice_obj = http.request.env['website.self.invoice.web'].sudo()
        try:
            auto_invoice = auto_invoice_obj.search([('order_number', '=', order_number),
                                                    ('rfc_partner', '=', rfc_partner.upper())])
            if auto_invoice:
                attachment_obj = http.request.env['website.self.invoice.web.attach'].sudo()
                attachments = attachment_obj.search([('website_auto_id', '=', auto_invoice[0].id)])
                return http.request.render('website_self_cfdi_invoice_ee.html_result_thnks',
                                           {
                                               'attachments': attachments,
                                           })
            else:
                error_message = "Su solicitud no pudo ser procesada.\nNo existe informacion para el Pedido %s." % order_number
                return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', {'errores': [error_message]})

        except:
            error_message = "Su solicitud no pudo ser procesada.\nLa informacion introducida es incorrecta."
            return http.request.render('website_self_cfdi_invoice_ee.html_result_error_inv', {'errores': [error_message]})

        return http.request.render('website_self_cfdi_invoice_ee.index',
            {
                'fields': ['RFC', 'Folio', ],
            })
        

class WebsiteAccount(CustomerPortal):
    OPTIONAL_BILLING_FIELDS = ["zipcode", "state_id", "vat", "company_name", "rfc", 'uso_cfdi']

    @route(['/my/account'], type='http', auth='user', website=True)
    def account(self, redirect=None, **post):
        if 'uso_cfdi' in post:
            uso_cfdi_id = http.request.env['catalogo.uso.cfdi'].sudo().search([('code', '=', post.get('uso_cfdi'))],
                                                                              limit=1)
            post.pop('uso_cfdi')
            post['uso_cfdi_id'] = uso_cfdi_id and uso_cfdi_id.id or False
        res = super(WebsiteAccount, self).account(redirect=redirect, **post)
        return res

