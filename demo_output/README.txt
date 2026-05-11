Demo del motor de plantillas DOCX
==================================

Esta carpeta contiene 3 archivos generados por el script demo_docx.py.
Abrelos en Word o LibreOffice para verificar el funcionamiento.

01_template_master.docx
  Plantilla original que el admin subio. Contiene placeholders <<...>>
  como <<RFC>>, <<NOMBRE_ESTACION>>, <<OBSERVACIONES>>, etc.

02_doc_aprobado.docx
  Documento generado a partir de la plantilla, con datos de la estacion
  ya rellenados automaticamente (RFC, razon social, permiso CRE...) y
  observaciones/hallazgos/medidas correctivas escritas por el admin.
  Estado: aprobado.

03_doc_borrador.docx
  Otro documento generado para la misma estacion pero con observaciones
  minimas. Estado: borrador.

Verifica que en los archivos 02 y 03:
  - <<RFC>> aparece como SES220315ABC
  - <<NOMBRE_ESTACION>> aparece como Estacion Las Choapas
  - <<PERMISO_CRE>> aparece como PL/12345/EXP/ES/2025
  - <<FECHA_HOY>> aparece con la fecha actual
  - Las observaciones/hallazgos son las que se escribieron al generar.
