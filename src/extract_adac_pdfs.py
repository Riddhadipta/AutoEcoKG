
from pathlib import Path
import pymupdf
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

PDF_FOLDER = ROOT / "data" / "raw" / "adac"
OUTPUT_FOLDER = ROOT / "data" / "intermediate"

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

records = []

pdf_files = sorted(PDF_FOLDER.glob("*.pdf"))

for pdf_file in pdf_files:
    try:
        with pymupdf.open(pdf_file) as document:
            text = "\n".join(
                page.get_text() for page in document
            )

            output_file = OUTPUT_FOLDER / (
                pdf_file.stem + ".txt"
            )

            output_file.write_text(
                text, encoding="utf-8"
            )

            records.append({
                "filename": pdf_file.name,
                "pages": len(document),
                "characters": len(text),
                "status": "success" if text.strip()
                          else "no_text"
            })

            print(f"[OK] {pdf_file.name}")

    except Exception as e:
        records.append({
            "filename": pdf_file.name,
            "status": "failed",
            "error": str(e)
        })

        print(f"[ERROR] {pdf_file.name}: {e}")

df = pd.DataFrame(records)

df.to_csv(
    OUTPUT_FOLDER / "extraction_summary.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\nExtraction completed.")
print(f"Total PDFs: {len(pdf_files)}")
print(df["status"].value_counts() if not df.empty
      else "No PDF files found.")
