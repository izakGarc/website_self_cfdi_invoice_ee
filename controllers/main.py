# -*- coding: utf-8 -*-
import logging
import re
import time

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class CfdiPortalController(http.Controller):

    # ─────────────────────────────────────────────────────────────
    # PASO 1 — Pantalla inicial: captura RFC y Folio
    # ─────────────────────────────────────────────────────────────
    @http.route('/portal/facturacliente/', auth='public', website=True, methods=['GET'])
    def portal_index(self, **kw):
        return request.render('website_self_cfdi_invoice_ee.index', {})

    # ─────────────────────────────────────────────────────────────
    # PASO 2 — Buscar el pedido y mostrar formulario de datos
    # ─────────────────────────────────────────────────────────────
    @http.route('/portal/facturacliente/rfc', type='http', auth='public',
                csrf=False, website=True, methods=['GET', 'POST'])
    def portal_buscar_pedido(self, **kwargs):
        order_number = (kwargs.get('order_number') or '').strip().upper()

        if not order_number:
            return request.render('website_self_cfdi_invoice_ee.html_result_error_inv',
                                  {'errores': ['El folio del pedido es obligatorio.']})

        order = request.env['sale.order'].sudo().search(
            [('name', '=', order_number), ('state', 'in', ('sale', 'done'))], limit=1
        )

        if not order:
            return request.render('website_self_cfdi_invoice_ee.html_result_error_inv',
                                  {'errores': ['No se encontró el pedido %s o aún no ha sido confirmado.' % order_number]})

        # Verificar si ya existe factura timbrada
        if order.invoice_ids.filtered(lambda inv: inv.state == 'posted' and inv.edi_state == 'sent'):
            return request.render('website_self_cfdi_invoice_ee.html_result_error_inv',
                                  {'errores': ['El pedido %s ya fue facturado.' % order_number]})

        partner = order.partner_id
        return request.render('website_self_cfdi_invoice_ee.facturacion', {
            'partner_name':       partner.name or '',
            'cp_post':            partner.zip or '',
            'correo_electronico': partner.email or '',
            'regimen_fiscal':     partner.l10n_mx_edi_fiscal_regime or '',
            'rfc_partner':        partner.vat or '',
            'order_number':       order.name,
            'monto_total':        order.amount_total,
        })

    # ─────────────────────────────────────────────────────────────
    # PASO 3 — Generar y timbrar la factura
    # ─────────────────────────────────────────────────────────────
    @http.route('/portal/facturacliente/results/', type='http', auth='public',
                csrf=False, website=True, methods=['POST'])
    def portal_generar_factura(self, **kwargs):

        # — Recoger parámetros —
        rfc             = (kwargs.get('rfc_partner') or '').strip().upper()
        order_number    = (kwargs.get('order_number') or '').strip().upper()
        monto_str       = (kwargs.get('monto_total') or '0').replace(',', '').strip()
        partner_name    = (kwargs.get('partner_name') or '').strip()
        correo          = (kwargs.get('correo_electronico') or '').strip()
        cp              = (kwargs.get('cp_post') or '').strip()
        regimen         = (kwargs.get('regimen_fiscal') or '').strip()
        uso_cfdi        = (kwargs.get('uso_del_cfdi') or '').strip()
        forma_pago_code = (kwargs.get('forma_de_pago_cfdi') or '').strip()

        def render_form(error):
            return request.render('website_self_cfdi_invoice_ee.facturacion', {
                'partner_name':       partner_name,
                'cp_post':            cp,
                'correo_electronico': correo,
                'regimen_fiscal':     regimen,
                'rfc_partner':        rfc,
                'order_number':       order_number,
                'monto_total':        monto_str,
                'uso_del_cfdi':       uso_cfdi,
                'forma_de_pago_cfdi': forma_pago_code,
                'error_timbrado':     error,
            })

        # — Validaciones —
        errores = []
        if not rfc:             errores.append('El RFC es obligatorio.')
        if not order_number:    errores.append('El Folio de Venta es obligatorio.')
        if not partner_name:    errores.append('El Nombre / Razón Social es obligatorio.')
        if not correo:          errores.append('El correo electrónico es obligatorio.')
        if not cp:              errores.append('El Código Postal es obligatorio.')
        if not regimen:         errores.append('El Régimen Fiscal es obligatorio.')
        if not uso_cfdi:        errores.append('El Uso del CFDI es obligatorio.')
        if not forma_pago_code: errores.append('La Forma de Pago es obligatoria.')

        try:
            monto = float(monto_str)
            if monto <= 0:
                errores.append('El monto total debe ser mayor a 0.')
        except (ValueError, AttributeError):
            errores.append('El monto total no es válido.')

        if errores:
            return request.render('website_self_cfdi_invoice_ee.html_result_error_inv', {'errores': errores})

        env = request.env

        # — Buscar forma de pago —
        payment_method = env['l10n_mx_edi.payment.method'].sudo().search(
            [('code', '=', forma_pago_code)], limit=1
        )
        if not payment_method:
            return render_form('Forma de pago no válida: %s' % forma_pago_code)

        # — Buscar pedido —
        order = env['sale.order'].sudo().search(
            [('name', '=', order_number), ('state', 'in', ('sale', 'done'))], limit=1
        )
        if not order:
            return request.render('website_self_cfdi_invoice_ee.html_result_error_inv',
                                  {'errores': ['Pedido %s no encontrado.' % order_number]})

        if order.invoice_ids.filtered(lambda inv: inv.state == 'posted' and inv.edi_state == 'sent'):
            return request.render('website_self_cfdi_invoice_ee.html_result_error_inv',
                                  {'errores': ['El pedido %s ya fue facturado.' % order_number]})

        company = order.company_id

        # — Buscar o crear partner —
        partner = env['res.partner'].sudo().search([('vat', '=', rfc)], limit=1)
        if partner:
            write_vals = {'name': partner_name, 'zip': cp, 'l10n_mx_edi_fiscal_regime': regimen}
            if correo and correo not in (partner.email or ''):
                write_vals['email'] = correo
            partner.sudo().write(write_vals)
        else:
            mexico = env['res.country'].sudo().search([('code', '=', 'MX')], limit=1)
            partner = env['res.partner'].sudo().create({
                'name': partner_name,
                'vat': rfc,
                'email': correo,
                'zip': cp,
                'l10n_mx_edi_fiscal_regime': regimen,
                'country_id': mexico.id,
            })

        # — Asignar forma de pago al pedido si no tiene —
        if not order.l10n_mx_edi_payment_method_id:
            order.sudo().write({'l10n_mx_edi_payment_method_id': payment_method.id})

        # — Crear factura —
        try:
            invoice = order.sudo().with_company(company.id)._create_invoices()
        except Exception as e:
            _logger.error('Error al crear factura para %s: %s', order_number, str(e))
            return request.render('website_self_cfdi_invoice_ee.html_result_error_inv',
                                  {'errores': ['Error al crear la factura. Contacte a soporte@loomber.com']})

        # — Asignar campos CFDI —
        vals = {
            'partner_id':                    partner.id,
            'l10n_mx_edi_usage':             uso_cfdi,
            'l10n_mx_edi_payment_policy':    'PUE',
            'l10n_mx_edi_payment_method_id': payment_method.id,
        }
        if hasattr(invoice, 'factura_cfdi'):
            vals['factura_cfdi'] = True
        invoice.sudo().write(vals)

        # — Validar factura (action_post) con compañía correcta —
        if invoice.state == 'draft':
            try:
                invoice.sudo().with_company(company.id).action_post()
            except Exception as e:
                _logger.error('Error al validar factura %s: %s', invoice.name, str(e))
                self._rollback_invoice(invoice, order)
                return request.render('website_self_cfdi_invoice_ee.html_result_error_inv',
                                      {'errores': ['Error al validar la factura. Contacte a soporte@loomber.com']})

        # — Timbrar EDI con compañía correcta —
        try:
            edi_docs = invoice.edi_document_ids.filtered(lambda d: d.state in ('to_send', 'to_cancel'))
            if edi_docs:
                edi_docs.sudo().with_company(company.id)._process_documents_web_services(with_commit=False)
        except Exception as e:
            _logger.error('Error EDI para %s: %s', invoice.name, str(e))

        # — Esperar resultado (máx 30 seg) —
        for _ in range(15):
            invoice.invalidate_recordset()
            if invoice.edi_state == 'sent':
                break
            if invoice.edi_document_ids.filtered(lambda d: d.error):
                break
            time.sleep(2)

        # — Verificar resultado final —
        invoice.invalidate_recordset()
        if invoice.edi_state != 'sent':
            edi_doc_error = invoice.edi_document_ids.filtered(lambda d: d.error)
            edi_error_raw = edi_doc_error[0].error if edi_doc_error else ''
            edi_error_clean = re.sub(r'<[^>]+>', ' ', edi_error_raw).strip()
            edi_error_clean = re.sub(r'\s+', ' ', edi_error_clean)
            _logger.warning('Timbrado fallido para %s: %s', order_number, edi_error_clean)
            self._rollback_invoice(invoice, order)
            return render_form(self._traducir_error_sat(edi_error_clean))

        # — Enviar correo con la factura —
        try:
            invoice.sudo().force_invoice_send()
        except Exception as e:
            _logger.warning('No se pudo enviar correo de factura: %s', str(e))

        return request.render('website_self_cfdi_invoice_ee.html_result_thnks', {})

    # ─────────────────────────────────────────────────────────────
    # Utilidad: traducir errores del SAT a mensajes amigables
    # ─────────────────────────────────────────────────────────────
    def _traducir_error_sat(self, error_raw):
        if not error_raw:
            return 'No se pudo timbrar la factura. Contacta a soporte@loomber.com'

        e = error_raw.lower()

        # RFC
        if 'rfc' in e and ('invalido' in e or 'inválido' in e or 'invalid' in e or 'no existe' in e):
            return 'El RFC ingresado no es válido o no está registrado en el SAT.'
        if 'rfc' in e and 'receptor' in e:
            return 'El RFC del receptor no es válido. Verifica que esté escrito correctamente.'
        if 'rfc' in e and 'emisor' in e:
            return 'Error en el RFC del emisor. Contacta a soporte@loomber.com'

        # Nombre / Razón Social
        if 'nombre' in e and ('receptor' in e or 'denominacion' in e or 'denominación' in e):
            return 'El Nombre o Razón Social no coincide con el RFC registrado en el SAT.'
        if 'denominacion' in e or 'denominación' in e:
            return 'El Nombre o Razón Social no coincide con el RFC registrado en el SAT.'

        # Régimen Fiscal
        if 'regimen' in e or 'régimen' in e:
            return 'El Régimen Fiscal no es compatible con tu RFC. Verifica que sea el correcto.'
        if 'regimenf' in e or 'regimenfiscal' in e:
            return 'El Régimen Fiscal seleccionado no corresponde al tipo de contribuyente.'

        # Uso CFDI
        if 'uso' in e and 'cfdi' in e:
            return 'El Uso del CFDI no es compatible con tu Régimen Fiscal.'
        if 'usocfdi' in e:
            return 'El Uso del CFDI no es compatible con tu Régimen Fiscal.'

        # Código Postal
        if 'codigo postal' in e or 'código postal' in e or 'codigopostal' in e or 'domicilio fiscal' in e:
            return 'El Código Postal no existe en el catálogo del SAT o no corresponde a tu RFC.'

        # Certificado / Sello
        if 'sello' in e or 'certificado' in e or 'certificate' in e:
            return 'Error en el certificado digital. Contacta a soporte@loomber.com'

        # Fecha
        if 'fecha' in e:
            return 'Error en la fecha de emisión. Contacta a soporte@loomber.com'

        # Impuestos
        if 'impuesto' in e or 'tax' in e or 'iva' in e:
            return 'Error en el cálculo de impuestos. Contacta a soporte@loomber.com'

        # Producto / UNSPSC
        if 'clave' in e and ('prod' in e or 'serv' in e):
            return 'Error en la clave de producto. Contacta a soporte@loomber.com'
        if 'unspsc' in e or 'claveprodserv' in e:
            return 'El producto no tiene una clave UNSPSC asignada. Contacta a soporte@loomber.com'

        # XML mal formado genérico
        if 'xml' in e or 'mal formado' in e or 'malformado' in e or '301' in e:
            return 'Los datos ingresados contienen un error de formato. Verifica tu RFC, Nombre y Código Postal.'

        # Error de conexión con el PAC
        if 'timeout' in e or 'connection' in e or 'conexion' in e or 'conexión' in e:
            return 'El servicio de timbrado no está disponible en este momento. Intenta en unos minutos.'

        # Duplicado
        if 'duplicado' in e or 'duplicate' in e or 'ya fue timbrado' in e:
            return 'Esta factura ya fue timbrada anteriormente.'

        # Genérico
        return 'No se pudo timbrar la factura. Verifica tus datos fiscales o contacta a soporte@loomber.com'

    # ─────────────────────────────────────────────────────────────
    # Utilidad: revertir factura si el timbrado falla
    # ─────────────────────────────────────────────────────────────
    def _rollback_invoice(self, invoice, order):
        try:
            if invoice.state == 'posted':
                invoice.sudo().button_cancel()
            if invoice.state in ('draft', 'cancel'):
                invoice.sudo().unlink()
            order.sudo().write({'invoice_status': 'to invoice'})
        except Exception as e:
            _logger.warning('No se pudo hacer rollback de factura: %s', str(e))