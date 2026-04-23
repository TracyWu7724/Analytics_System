import os
import re

import pandas as pd



def clean_column_name(col_name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", str(col_name)).strip("_")
    if cleaned and cleaned[0].isdigit():
        cleaned = f"col_{cleaned}"
    return cleaned or "unnamed_column"


class UploadService:
    def __init__(self, data_service):
        self.data_service = data_service

    def get_uploaded_table_columns(self, table_name: str, db_path: str) -> list[str]:
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            return [row[1] for row in cursor.fetchall()]
        finally:
            conn.close()

    def process_uploaded_file(self, file_path: str, filename: str) -> dict:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(file_path)
        elif filename.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(file_path)
        else:
            raise ValueError("Unsupported file format")

        df.columns = [clean_column_name(col) for col in df.columns]
        seen: dict[str, int] = {}
        deduped_columns = []
        for col in df.columns:
            seen[col] = seen.get(col, -1) + 1
            deduped_columns.append(f"{col}_{seen[col]}" if seen[col] else col)
        df.columns = deduped_columns

        table_name = f"uploaded_{clean_column_name(os.path.splitext(filename)[0])}"
        file_extension = os.path.splitext(filename)[1].lower()
        result = self.data_service.handle_uploaded_file(df, table_name, filename, file_extension)
        if result["success"]:
            result["original_filename"] = filename
            result["file_extension"] = file_extension
        return result
