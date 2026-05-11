"""DOCX → PDF conversion (stub).

The real conversion strategy is deferred until we pick between:

* **LibreOffice headless** — ``soffice --headless --convert-to pdf``. Free,
  high-fidelity, but adds a ~400 MB system dependency on the deployment host.
* **docx2pdf** (Word COM) — Windows-only, requires a licensed Word install.
* **Aspose.Words** — commercial, no system deps.
* **DOCX-only delivery** — punt on PDF entirely; users open the .docx in
  Word/Drive and save as PDF themselves.

Until that decision is made, :func:`convert_to_pdf` returns ``None`` and
callers must treat that as the normal outcome ("PDF not generated"). The
generated-documents flow already handles a missing ``pdf_path`` — admins
download the .docx in the meantime.

When the conversion backend is chosen, replace the body of
:func:`convert_to_pdf` with the real implementation. Every caller that wires
this in already deals with the ``None`` case, so swapping in a real backend
is a single-file change.
"""

from __future__ import annotations

from pathlib import Path


def convert_to_pdf(docx_path: str | Path, output_pdf_path: str | Path) -> Path | None:
    """Convert a ``.docx`` to PDF.

    Parameters
    ----------
    docx_path:
        Source ``.docx`` file (must exist).
    output_pdf_path:
        Where to write the resulting PDF.

    Returns
    -------
    Path | None
        Path to the produced PDF, or ``None`` when no backend is configured
        (current behavior). Real implementations must:

        * Honor ``output_pdf_path`` exactly (don't relocate the file).
        * Raise an exception on conversion failure rather than returning
          ``None`` — ``None`` is reserved for "feature not configured".
    """
    # Intentionally a no-op for now. See module docstring.
    _ = (docx_path, output_pdf_path)
    return None


def is_available() -> bool:
    """Whether a real PDF conversion backend is wired up.

    Routes can use this to decide whether to advertise a "Download PDF" button
    in the UI. Currently always ``False``.
    """
    return False
