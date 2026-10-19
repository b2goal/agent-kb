"""Customer list export (used by the CRM sync). Columns: id, name, email."""
import csv
import io


def export_customers_csv(conn):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["id", "name", "email"])
    for c in conn.execute("SELECT * FROM customers ORDER BY id"):
        w.writerow([c["id"], c["name"], c["email"]])
    return out.getvalue()
