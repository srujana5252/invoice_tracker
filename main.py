import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "invoice_data.db"
PDF_DIR = APP_DIR / "invoices"
PDF_DIR.mkdir(exist_ok=True)


def money(value):
    """Format a number as Indian rupees."""
    return f"₹{Decimal(str(value)):,.2f}"


def decimal_value(text, field_name, allow_zero=True):
    try:
        value = Decimal(text.strip())
        if not value.is_finite():
            raise InvalidOperation
        if value < 0 or (not allow_zero and value == 0):
            raise ValueError
        return value
    except (InvalidOperation, ValueError, AttributeError):
        rule = "zero or greater" if allow_zero else "greater than zero"
        raise ValueError(f"{field_name} must be a valid number {rule}.")
def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    with connect_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            address TEXT
        );

        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            invoice_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            discount TEXT NOT NULL DEFAULT '0',
            tax_rate TEXT NOT NULL DEFAULT '0',
            subtotal TEXT NOT NULL,
            total TEXT NOT NULL,
            notes TEXT DEFAULT '',
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        );

        CREATE TABLE IF NOT EXISTS invoice_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            quantity TEXT NOT NULL,
            unit_price TEXT NOT NULL,
            line_total TEXT NOT NULL,
            FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL,
            amount TEXT NOT NULL,
            payment_date TEXT NOT NULL,
            method TEXT NOT NULL,
            note TEXT DEFAULT '',
            FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id)
                ON DELETE CASCADE
        );
        """)
def invoice_number(invoice_id):
    return f"INV-{invoice_id:04d}"


def get_invoice_summary(invoice_id):
    with connect_db() as conn:
        invoice = conn.execute("""
            SELECT i.total, i.due_date, COALESCE(SUM(CAST(p.amount AS REAL)), 0)
            FROM invoices i
            LEFT JOIN payments p ON p.invoice_id = i.invoice_id
            WHERE i.invoice_id = ?
            GROUP BY i.invoice_id
        """, (invoice_id,)).fetchone()

    if not invoice:
        return None

    total = Decimal(invoice[0])
    paid = Decimal(str(invoice[2])).quantize(Decimal("0.01"))
    balance = max(Decimal("0.00"), total - paid)

    if balance == 0:
        status = "Paid"
    elif invoice[1] < date.today().isoformat():
        status = "Overdue"
    elif paid > 0:
        status = "Partially paid"
    else:
        status = "Pending"

    return total, paid, balance, status, invoice[1]
def create_invoice_pdf(invoice_id, destination=None):
    with connect_db() as conn:
        invoice = conn.execute("""
            SELECT i.invoice_date, i.due_date, i.discount, i.tax_rate,
                   i.subtotal, i.total, i.notes,
                   c.name, c.email, c.phone, c.address
            FROM invoices i
            JOIN customers c ON c.customer_id = i.customer_id
            WHERE i.invoice_id = ?
        """, (invoice_id,)).fetchone()

        items = conn.execute("""
            SELECT description, quantity, unit_price, line_total
            FROM invoice_items WHERE invoice_id = ?
        """, (invoice_id,)).fetchall()

        payments = conn.execute("""
            SELECT amount, payment_date, method, note
            FROM payments WHERE invoice_id = ?
            ORDER BY payment_id
        """, (invoice_id,)).fetchall()
        if not invoice:
            raise ValueError("Invoice not found.")

    (invoice_date, due_date, discount, tax_rate, subtotal, total, notes,
     customer_name, email, phone, address) = invoice
    summary = get_invoice_summary(invoice_id)
    total_amount, paid, balance, status, _ = summary

    if destination is None:
        destination = PDF_DIR / f"{invoice_number(invoice_id)}.pdf"

    styles = getSampleStyleSheet()
    story = [
        Paragraph("INVOICE", styles["Title"]),
        Paragraph("Freelance / Small Business Services", styles["Heading2"]),
        Spacer(1, 5 * mm),
        Paragraph(f"<b>Invoice number:</b> {invoice_number(invoice_id)}", styles["Normal"]),
        Paragraph(f"<b>Invoice date:</b> {invoice_date}", styles["Normal"]),
        Paragraph(f"<b>Due date:</b> {due_date}", styles["Normal"]),
        Spacer(1, 5 * mm),
        Paragraph("<b>Bill to</b>", styles["Heading3"]),
        Paragraph(customer_name, styles["Normal"]),
        Paragraph(f"Email: {email or '-'}", styles["Normal"]),
        Paragraph(f"Phone: {phone or '-'}", styles["Normal"]),
        Paragraph(f"Address: {address or '-'}", styles["Normal"]),
        Spacer(1, 6 * mm),
    ]
    table_data = [["Description", "Quantity", "Unit price", "Amount"]]
    for description, quantity, unit_price, line_total in items:
        table_data.append([
            Paragraph(str(description).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), styles["BodyText"]),
            quantity,
            money(unit_price),
            money(line_total)
        ])

    item_table = Table(table_data, colWidths=[85 * mm, 25 * mm, 35 * mm, 35 * mm], repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243b53")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([item_table, Spacer(1, 5 * mm)])

    tax_base = max(Decimal("0"), Decimal(subtotal) - Decimal(discount))
    tax_amount = (tax_base * Decimal(tax_rate) / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    totals_data = [
        ["Subtotal", money(subtotal)],
        ["Discount", money(discount)],
        [f"Tax ({tax_rate}%)", money(tax_amount)],
        ["Total", money(total)],
        ["Paid", money(paid)],
        ["Balance due", money(balance)],
        ["Status", status],
    ]
    totals_table = Table(totals_data, colWidths=[45 * mm, 35 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 3), (-1, 3), 0.8, colors.black),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
        ("FONTNAME", (0, 5), (-1, 5), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(totals_table)

    if payments:
        story.extend([Spacer(1, 5 * mm), Paragraph("Payment history", styles["Heading3"])])
        payment_data = [["Date", "Method", "Amount", "Note"]]
        for amount, payment_date, method, note in payments:
            payment_data.append([payment_date, method, money(amount), note or "-"])
        payment_table = Table(payment_data, colWidths=[30 * mm, 35 * mm, 30 * mm, 65 * mm])
        payment_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef4")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(payment_table)

    if notes:
        story.extend([Spacer(1, 5 * mm), Paragraph("Notes", styles["Heading3"]),
                      Paragraph(str(notes).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), styles["BodyText"])])

    story.extend([Spacer(1, 8 * mm),
                  Paragraph("Thank you for your business.", styles["Italic"])])

    doc = SimpleDocTemplate(
        str(destination), pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm
    )
    doc.build(story)
    return Path(destination)
class InvoiceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Invoice Generator and Payment Tracker")
        self.root.geometry("1100x760")
        self.root.minsize(900, 620)

        self.items = []
        self.selected_invoice_id = None

        self.build_ui()
        self.refresh_invoices()

    def build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.invoice_tab = ttk.Frame(notebook, padding=12)
        self.payment_tab = ttk.Frame(notebook, padding=12)
        self.history_tab = ttk.Frame(notebook, padding=12)

        notebook.add(self.invoice_tab, text="Create Invoice")
        notebook.add(self.payment_tab, text="Record Payment")
        notebook.add(self.history_tab, text="Invoice History")

        self.build_invoice_tab()
        self.build_payment_tab()
        self.build_history_tab()
    def build_invoice_tab(self):
        tab = self.invoice_tab
        customer = ttk.LabelFrame(tab, text="Customer details", padding=10)
        customer.pack(fill="x")

        self.customer_name = tk.StringVar()
        self.customer_email = tk.StringVar()
        self.customer_phone = tk.StringVar()
        self.customer_address = tk.StringVar()
        self.invoice_date = tk.StringVar(value=date.today().isoformat())
        self.due_date = tk.StringVar(value=date.today().isoformat())

        fields = [
            ("Name *", self.customer_name),
            ("Email", self.customer_email),
            ("Phone", self.customer_phone),
            ("Address", self.customer_address),
            ("Invoice date (YYYY-MM-DD)", self.invoice_date),
            ("Due date (YYYY-MM-DD)", self.due_date),
        ]
        for index, (label, variable) in enumerate(fields):
            row, col = divmod(index, 3)
            ttk.Label(customer, text=label).grid(row=row * 2, column=col, sticky="w", padx=5, pady=(2, 0))
            ttk.Entry(customer, textvariable=variable, width=31).grid(
                row=row * 2 + 1, column=col, sticky="ew", padx=5, pady=(0, 6)
            )
        for col in range(3):
            customer.columnconfigure(col, weight=1)

        item_box = ttk.LabelFrame(tab, text="Invoice items", padding=10)
        item_box.pack(fill="both", expand=True, pady=10)

        self.item_description = tk.StringVar()
        self.item_quantity = tk.StringVar(value="1")
        self.item_price = tk.StringVar(value="0.00")

        entry_row = ttk.Frame(item_box)
        entry_row.pack(fill="x")
        ttk.Label(entry_row, text="Description").grid(row=0, column=0, sticky="w")
        ttk.Label(entry_row, text="Quantity").grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(entry_row, text="Unit price (₹)").grid(row=0, column=2, sticky="w", padx=5)
        ttk.Entry(entry_row, textvariable=self.item_description, width=40).grid(row=1, column=0, sticky="ew")
        ttk.Entry(entry_row, textvariable=self.item_quantity, width=12).grid(row=1, column=1, padx=5)
        ttk.Entry(entry_row, textvariable=self.item_price, width=15).grid(row=1, column=2, padx=5)
        ttk.Button(entry_row, text="Add item", command=self.add_item).grid(row=1, column=3, padx=5)
        entry_row.columnconfigure(0, weight=1)
        self.item_tree = ttk.Treeview(
            item_box, columns=("description", "quantity", "price", "amount"),
            show="headings", height=7
        )
        for col, heading, width in [
            ("description", "Description", 430),
            ("quantity", "Quantity", 100),
            ("price", "Unit price", 130),
            ("amount", "Amount", 130),
        ]:
            self.item_tree.heading(col, text=heading)
            self.item_tree.column(col, width=width, anchor="w" if col == "description" else "e")
        self.item_tree.pack(fill="both", expand=True, pady=8)
        ttk.Button(item_box, text="Remove selected item", command=self.remove_item).pack(anchor="e")

        bottom = ttk.Frame(tab)
        bottom.pack(fill="x")
        self.discount = tk.StringVar(value="0")
        self.tax_rate = tk.StringVar(value="0")
        self.notes = tk.StringVar()
        ttk.Label(bottom, text="Discount (₹)").grid(row=0, column=0, sticky="w")
        ttk.Entry(bottom, textvariable=self.discount, width=12).grid(row=0, column=1, padx=5)
        ttk.Label(bottom, text="Tax rate (%)").grid(row=0, column=2, sticky="w")
        ttk.Entry(bottom, textvariable=self.tax_rate, width=12).grid(row=0, column=3, padx=5)
        ttk.Label(bottom, text="Notes").grid(row=0, column=4, sticky="w")
        ttk.Entry(bottom, textvariable=self.notes, width=30).grid(row=0, column=5, padx=5, sticky="ew")
        ttk.Button(bottom, text="Create invoice + PDF", command=self.save_invoice).grid(
            row=1, column=0, columnspan=6, sticky="ew", pady=(12, 0)
        )
        bottom.columnconfigure(5, weight=1)
    def add_item(self):
        description = self.item_description.get().strip()
        if not description:
            messagebox.showerror("Missing description", "Enter an item or service description.")
            return
        try:
            quantity = decimal_value(self.item_quantity.get(), "Quantity", allow_zero=False)
            price = decimal_value(self.item_price.get(), "Unit price")
        except ValueError as exc:
            messagebox.showerror("Invalid item", str(exc))
            return

        line_total = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.items.append({
            "description": description,
            "quantity": quantity,
            "unit_price": price,
            "line_total": line_total,
        })
        self.item_tree.insert("", "end", values=(
            description, str(quantity), money(price), money(line_total)
        ))
        self.item_description.set("")
        self.item_quantity.set("1")
        self.item_price.set("0.00")

    def remove_item(self):
        selected = self.item_tree.selection()
        if not selected:
            messagebox.showinfo("Select item", "Select an item to remove.")
            return
        indexes = sorted((self.item_tree.index(i) for i in selected), reverse=True)
        for index in indexes:
            del self.items[index]
        for item in self.item_tree.get_children():
            self.item_tree.delete(item)
        for item in self.items:
            self.item_tree.insert("", "end", values=(
                item["description"], str(item["quantity"]),
                money(item["unit_price"]), money(item["line_total"])
            ))
    def save_invoice(self):
        name = self.customer_name.get().strip()
        if not name:
            messagebox.showerror("Missing customer", "Enter the customer name.")
            return
        if not self.items:
            messagebox.showerror("No items", "Add at least one invoice item.")
            return

        try:
            invoice_date = date.fromisoformat(self.invoice_date.get().strip())
            due_date = date.fromisoformat(self.due_date.get().strip())
            if due_date < invoice_date:
                raise ValueError("Due date cannot be earlier than invoice date.")
            discount = decimal_value(self.discount.get(), "Discount")
            tax_rate = decimal_value(self.tax_rate.get(), "Tax rate")
            subtotal = sum((item["line_total"] for item in self.items), Decimal("0.00"))
            if discount > subtotal:
                raise ValueError("Discount cannot exceed the subtotal.")
            taxable = subtotal - discount
            tax_amount = (taxable * tax_rate / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            total = taxable + tax_amount
        except (ValueError, InvalidOperation) as exc:
            messagebox.showerror("Invalid invoice", str(exc))
            return

        try:
            with connect_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO customers (name, email, phone, address)
                    VALUES (?, ?, ?, ?)
                """, (
                    name, self.customer_email.get().strip(),
                    self.customer_phone.get().strip(),
                    self.customer_address.get().strip()
                ))
                customer_id = cursor.lastrowid

                cursor = conn.execute("""
                    INSERT INTO invoices
                    (customer_id, invoice_date, due_date, discount, tax_rate,
                     subtotal, total, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    customer_id, invoice_date.isoformat(), due_date.isoformat(),
                    str(discount), str(tax_rate), str(subtotal), str(total),
                    self.notes.get().strip()
                ))
                new_invoice_id = cursor.lastrowid
                for item in self.items:
                    conn.execute("""
                        INSERT INTO invoice_items
                        (invoice_id, description, quantity, unit_price, line_total)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        new_invoice_id, item["description"], str(item["quantity"]),
                        str(item["unit_price"]), str(item["line_total"])
                    ))

            pdf_path = create_invoice_pdf(new_invoice_id)
            messagebox.showinfo(
                "Invoice created",
                f"Invoice {invoice_number(new_invoice_id)} created successfully.\n\n"
                f"Total: {money(total)}\nPDF saved to:\n{pdf_path}"
            )
            self.items.clear()
            for item in self.item_tree.get_children():
                self.item_tree.delete(item)
            self.refresh_invoices()
        except Exception as exc:
            messagebox.showerror("Error", f"Could not create invoice:\n{exc}")
    def build_payment_tab(self):
        tab = self.payment_tab
        form = ttk.LabelFrame(tab, text="Record a payment", padding=12)
        form.pack(fill="x", anchor="n")

        self.payment_invoice = tk.StringVar()
        self.payment_amount = tk.StringVar()
        self.payment_date = tk.StringVar(value=date.today().isoformat())
        self.payment_method = tk.StringVar(value="Bank transfer")
        self.payment_note = tk.StringVar()

        ttk.Label(form, text="Invoice").grid(row=0, column=0, sticky="w", pady=5)
        self.payment_invoice_combo = ttk.Combobox(
            form, textvariable=self.payment_invoice, state="readonly", width=35
        )
        self.payment_invoice_combo.grid(row=0, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(form, text="Amount (₹)").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.payment_amount).grid(row=1, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(form, text="Payment date (YYYY-MM-DD)").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.payment_date).grid(row=2, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(form, text="Method").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Combobox(
            form, textvariable=self.payment_method,
            values=["Cash", "UPI", "Bank transfer", "Card", "Other"],
            state="readonly"
        ).grid(row=3, column=1, sticky="ew", padx=8, pady=5)
        ttk.Label(form, text="Note").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(form, textvariable=self.payment_note).grid(row=4, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(form, text="Save payment", command=self.save_payment).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=10
        )
        form.columnconfigure(1, weight=1)

        self.payment_summary = ttk.Label(tab, text="Select an invoice to see its balance.")
        self.payment_summary.pack(anchor="w", pady=12)
        self.payment_invoice_combo.bind("<<ComboboxSelected>>", self.show_payment_summary)
    def build_history_tab(self):
        tab = self.history_tab
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 8))
        self.search_var = tk.StringVar()
        ttk.Label(top, text="Search invoice/customer").pack(side="left")
        search_entry = ttk.Entry(top, textvariable=self.search_var, width=30)
        search_entry.pack(side="left", padx=8)
        search_entry.bind("<KeyRelease>", lambda _event: self.refresh_invoices())
        ttk.Button(top, text="Refresh", command=self.refresh_invoices).pack(side="left", padx=4)
        ttk.Button(top, text="Save/open PDF copy", command=self.export_selected_pdf).pack(side="left", padx=4)

        columns = ("number", "customer", "date", "due", "total", "paid", "balance", "status")
        self.history_tree = ttk.Treeview(tab, columns=columns, show="headings")
        headings = [
            ("number", "Invoice", 90), ("customer", "Customer", 170),
            ("date", "Invoice date", 100), ("due", "Due date", 100),
            ("total", "Total", 100), ("paid", "Paid", 100),
            ("balance", "Balance", 100), ("status", "Status", 120)
        ]
        for col, title, width in headings:
            self.history_tree.heading(col, text=title)
            self.history_tree.column(col, width=width, anchor="w" if col in ("number", "customer", "status") else "e")
        self.history_tree.pack(fill="both", expand=True)
        self.history_tree.bind("<<TreeviewSelect>>", self.on_history_select)

        self.summary_label = ttk.Label(tab, text="")
        self.summary_label.pack(anchor="w", pady=(8, 0))
    def refresh_invoices(self):
        if not hasattr(self, "history_tree"):
            return
        for row in self.history_tree.get_children():
            self.history_tree.delete(row)

        query = self.search_var.get().strip() if hasattr(self, "search_var") else ""
        with connect_db() as conn:
            rows = conn.execute("""
                SELECT i.invoice_id, c.name, i.invoice_date, i.due_date, i.total
                FROM invoices i
                JOIN customers c ON c.customer_id = i.customer_id
                WHERE c.name LIKE ? OR CAST(i.invoice_id AS TEXT) LIKE ?
                ORDER BY i.invoice_id DESC
            """, (f"%{query}%", f"%{query}%")).fetchall()

        total_invoiced = Decimal("0")
        total_paid = Decimal("0")
        total_outstanding = Decimal("0")
        for invoice_id, customer, inv_date, due_date, total_str in rows:
            summary = get_invoice_summary(invoice_id)
            total, paid, balance, status, _ = summary
            total_invoiced += total
            total_paid += paid
            total_outstanding += balance
            self.history_tree.insert("", "end", iid=str(invoice_id), values=(
                invoice_number(invoice_id), customer, inv_date, due_date,
                money(total), money(paid), money(balance), status
            ))

        self.summary_label.config(
            text=f"Shown invoices — Total: {money(total_invoiced)}   "
                 f"Collected: {money(total_paid)}   Outstanding: {money(total_outstanding)}"
        )
        self.update_payment_invoice_choices()

    def update_payment_invoice_choices(self):
        if not hasattr(self, "payment_invoice_combo"):
            return
        with connect_db() as conn:
            rows = conn.execute("""
                SELECT i.invoice_id, c.name
                FROM invoices i JOIN customers c ON c.customer_id = i.customer_id
                ORDER BY i.invoice_id DESC
            """).fetchall()
        self.invoice_choice_map = {
            f"{invoice_number(i)} - {name}": i for i, name in rows
        }
        values = list(self.invoice_choice_map.keys())
        self.payment_invoice_combo["values"] = values
        if self.payment_invoice.get() not in values:
            self.payment_invoice.set(values[0] if values else "")
        self.show_payment_summary()
    def show_payment_summary(self, _event=None):
        if not hasattr(self, "payment_summary"):
            return
        invoice_id = self.invoice_choice_map.get(self.payment_invoice.get()) if hasattr(self, "invoice_choice_map") else None
        if not invoice_id:
            self.payment_summary.config(text="No invoices available.")
            return
        summary = get_invoice_summary(invoice_id)
        total, paid, balance, status, due_date = summary
        self.payment_summary.config(
            text=f"Total: {money(total)} | Paid: {money(paid)} | "
                 f"Balance: {money(balance)} | Status: {status} | Due: {due_date}"
        )

    def save_payment(self):
        invoice_id = getattr(self, "invoice_choice_map", {}).get(self.payment_invoice.get())
        if not invoice_id:
            messagebox.showerror("Select invoice", "Create or select an invoice first.")
            return
        try:
            amount = decimal_value(self.payment_amount.get(), "Payment amount", allow_zero=False)
            payment_date = date.fromisoformat(self.payment_date.get().strip())
            summary = get_invoice_summary(invoice_id)
            if amount > summary[2]:
                raise ValueError(f"Payment cannot exceed the remaining balance of {money(summary[2])}.")
        except ValueError as exc:
            messagebox.showerror("Invalid payment", str(exc))
            return

        with connect_db() as conn:
            conn.execute("""
                INSERT INTO payments (invoice_id, amount, payment_date, method, note)
                VALUES (?, ?, ?, ?, ?)
            """, (
                invoice_id, str(amount), payment_date.isoformat(),
                self.payment_method.get(), self.payment_note.get().strip()
            ))

        messagebox.showinfo("Payment saved", "Payment recorded successfully.")
        self.payment_amount.set("")
        self.payment_note.set("")
        self.refresh_invoices()
        self.show_payment_summary()

    def on_history_select(self, _event=None):
        selected = self.history_tree.selection()
        if selected:
            self.selected_invoice_id = int(selected[0])

    def export_selected_pdf(self):
        if not self.history_tree.selection():
            messagebox.showinfo("Select invoice", "Select an invoice in the history table first.")
            return
        invoice_id = int(self.history_tree.selection()[0])
        target = filedialog.asksaveasfilename(
            title="Save invoice PDF",
            initialfile=f"{invoice_number(invoice_id)}.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")]
        )
        if not target:
            return
        try:
            path = create_invoice_pdf(invoice_id, target)
            messagebox.showinfo("PDF saved", f"Invoice PDF saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("PDF error", str(exc))


def main():
    initialize_database()
    root = tk.Tk()
    app = InvoiceApp(root)
    root.mainloop()
if __name__ == "__main__":
    main()

        
