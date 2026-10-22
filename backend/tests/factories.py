"""Builds realistic fixture documents (PDF receipts, statements) in memory for tests and the fixtures folder."""
import io


def receipt_pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    y = 560
    c.setFont("Courier", 9)
    for ln in lines:
        c.drawString(24, y, ln)
        y -= 13
    c.save()
    return buf.getvalue()


GROCERY_RECEIPT = [
    "FRESH MART SUPERMARKET",
    "MG Road, Thampanoor, Trivandrum - 695001",
    "GSTIN: 32ABCDE1234F1Z5   Ph: 0471-2345678",
    "TAX INVOICE",
    "Bill No: FM-20481          Date: 18/10/2026  Time: 19:42",
    "Item                     Qty    Rate     Amount",
    "Rice Ponni 5kg            1    320.00    320.00",
    "Milk 1L                   2     30.00     60.00",
    "Bread Brown               1     45.00     45.00",
    "Lifebuoy Soap             3     15.00     45.00",
    "Surf Excel Detergent 1kg  1    130.00    130.00",
    "Sub Total                                 600.00",
    "Discount                                   20.00",
    "CGST 2.5%                                   7.50",
    "SGST 2.5%                                   7.50",
    "Grand Total                          Rs. 595.00",
    "Paid by UPI   UPI Ref No: 429187654321",
    "Thank you! Visit again",
]

RESTAURANT_RECEIPT = [
    "ABC Restaurant",
    "12, Statue Junction, Trivandrum",
    "Invoice No: ABC/2026/7781",
    "Date: 18-10-2026 21:05",
    "Paneer Butter Masala      1   260.00   260.00",
    "Butter Naan               2    40.00    80.00",
    "Fresh Lime Soda           2    50.00   100.00",
    "Sub Total                               440.00",
    "Service Charge                           10.00",
    "Total                               ₹ 450.00",
    "Payment: Cash",
]

UPI_SCREENSHOT_TEXT = """Payment successful
₹450
Paid to
ABC Restaurant
abcrestaurant@okaxis
18 Oct 2026, 9:07 PM
UPI transaction ID: 429112345678
Google Pay"""

BANK_CSV = """Statement of Account - XYZ Bank
Account: XXXX1234
Txn Date,Narration,Ref No,Withdrawal Amt,Deposit Amt,Closing Balance
18/10/2026,UPI/DR/429112345678/ABC RESTAURANT/SBIN/abcrest@okaxis/dinner,429112345678,450.00,,24550.00
18/10/2026,UPI/DR/429187654321/FRESHMART TRIVANDRUM/HDFC/freshmart@ybl/Payment,429187654321,595.00,,23955.00
19/10/2026,NEFT-SALARY ACME CORP OCT,N2926101912345,,85000.00,108955.00
20/10/2026,CC PAYMENT XXXX4321 AUTOPAY,CC000123,12000.00,,96955.00
21/10/2026,UPI/DR/429199990000/RAHUL K/YESB/rahul@ybl/dinner share,429199990000,300.00,,96655.00
"""
