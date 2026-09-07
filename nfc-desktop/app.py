import sys
import tkinter as tk
from tkinter import ttk, messagebox
import database
from nfc_worker import NFCWorker

# Serial port configuration: Update to COM port (Windows) or /dev/ttyUSB0 (Linux)
DEFAULT_PORT = "COM4" 

class FoodCourtApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Food Court Cashless System (Desktop)")
        self.geometry("640x620")
        self.resizable(False, False)

        # Initialize persistence layer
        database.initialize_database()

        # Application state
        self.current_mode = tk.StringVar(value="CHECK")
        self.amount_input = tk.StringVar(value="50")
        self.latest_uid = tk.StringVar(value="--:--:--:--:--:--:--")
        
        self._build_ui()

        # Launch hardware interface
        self.nfc_worker = NFCWorker(
            port=DEFAULT_PORT,
            on_tag_detected=self._handle_tag_detected
        )
        self.nfc_worker.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        """Construct GUI widgets."""
        main_frame = ttk.Frame(self, padding="16")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header Section
        header_lbl = ttk.Label(
            main_frame, 
            text="Food Court NFC Terminal", 
            font=("Helvetica", 16, "bold")
        )
        header_lbl.pack(pady=(0, 12))

        # Mode Selection Frame
        mode_frame = ttk.LabelFrame(main_frame, text="Terminal Operation Mode", padding="10")
        mode_frame.pack(fill=tk.X, pady=6)

        ttk.Radiobutton(
            mode_frame, text="Check Balance", value="CHECK", variable=self.current_mode
        ).pack(side=tk.LEFT, padx=12)
        ttk.Radiobutton(
            mode_frame, text="Cashier (Top-up)", value="TOP_UP", variable=self.current_mode
        ).pack(side=tk.LEFT, padx=12)
        ttk.Radiobutton(
            mode_frame, text="Stall POS (Payment)", value="PAY", variable=self.current_mode
        ).pack(side=tk.LEFT, padx=12)

        # Parameter Input Frame
        param_frame = ttk.LabelFrame(main_frame, text="Transaction Parameters", padding="10")
        param_frame.pack(fill=tk.X, pady=6)

        ttk.Label(param_frame, text="Amount (THB):").pack(side=tk.LEFT, padx=6)
        amt_entry = ttk.Entry(param_frame, textvariable=self.amount_input, width=12)
        amt_entry.pack(side=tk.LEFT, padx=6)

        # Shortcut Preset Buttons
        ttk.Button(param_frame, text="40", command=lambda: self.amount_input.set("40")).pack(side=tk.LEFT, padx=2)
        ttk.Button(param_frame, text="50", command=lambda: self.amount_input.set("50")).pack(side=tk.LEFT, padx=2)
        ttk.Button(param_frame, text="100", command=lambda: self.amount_input.set("100")).pack(side=tk.LEFT, padx=2)

        # Real-time Status Card Frame
        status_frame = ttk.LabelFrame(main_frame, text="Active Card Readout", padding="10")
        status_frame.pack(fill=tk.X, pady=6)

        ttk.Label(status_frame, text="UID:").grid(row=0, column=0, sticky=tk.W)
        self.uid_lbl = ttk.Label(status_frame, textvariable=self.latest_uid, font=("Consolas", 12, "bold"))
        self.uid_lbl.grid(row=0, column=1, sticky=tk.W, padx=6)

        self.log_text = tk.Text(status_frame, height=5, state=tk.DISABLED, bg="#F4F4F4")
        self.log_text.grid(row=1, column=0, columnspan=2, pady=6, sticky=tk.EW)

        # Recent Transactions Audit Frame
        audit_frame = ttk.LabelFrame(main_frame, text="Recent Transactions Ledger", padding="10")
        audit_frame.pack(fill=tk.BOTH, expand=True, pady=6)

        columns = ("id", "uid", "type", "amount", "balance", "time")
        self.tree = ttk.Treeview(audit_frame, columns=columns, show="headings", height=6)
        
        self.tree.heading("id", text="ID")
        self.tree.heading("uid", text="Card UID")
        self.tree.heading("type", text="Action")
        self.tree.heading("amount", text="Amount")
        self.tree.heading("balance", text="Balance")
        self.tree.heading("time", text="Timestamp")

        self.tree.column("id", width=40, anchor=tk.CENTER)
        self.tree.column("uid", width=130, anchor=tk.CENTER)
        self.tree.column("type", width=80, anchor=tk.CENTER)
        self.tree.column("amount", width=70, anchor=tk.E)
        self.tree.column("balance", width=80, anchor=tk.E)
        self.tree.column("time", width=140, anchor=tk.CENTER)
        
        self.tree.pack(fill=tk.BOTH, expand=True)
        self._refresh_ledger()

    def _handle_tag_detected(self, uid_str: str) -> None:
        """Safely schedule UI update and transaction processing on main GUI thread."""
        self.after(0, self._process_card_action, uid_str)

    def _process_card_action(self, uid: str) -> None:
        """Dispatch financial logic according to selected terminal mode."""
        self.latest_uid.set(uid)
        mode = self.current_mode.get()

        try:
            amount = float(self.amount_input.get())
        except ValueError:
            self._log_message("Invalid amount entered. Please enter a valid number.")
            return

        if mode == "CHECK":
            wallet = database.get_wallet(uid)
            if wallet is None:
                database.register_card_if_absent(uid)
                self._log_message(f"Card registered. UID: {uid} | Balance: 0.00 THB")
            else:
                self._log_message(f"Card detected. UID: {uid} | Current Balance: {wallet['balance']:.2f} THB")

        elif mode == "TOP_UP":
            success, msg, balance = database.process_top_up(uid, amount)
            self._log_message(f"[{msg}] Added {amount:.2f} THB. Current Balance: {balance:.2f} THB")

        elif mode == "PAY":
            success, msg, balance = database.process_deduction(uid, amount)
            if success:
                self._log_message(f"[{msg}] Paid {amount:.2f} THB. Remaining Balance: {balance:.2f} THB")
            else:
                self._log_message(f"[REJECTED] {msg}")

        self._refresh_ledger()

    def _log_message(self, message: str) -> None:
        """Append log message to the status view."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert(tk.END, message)
        self.log_text.config(state=tk.DISABLED)

    def _refresh_ledger(self) -> None:
        """Reload recent transaction records into the audit tree view."""
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        records = database.get_recent_transactions(10)
        for row in records:
            self.tree.insert("", tk.END, values=(
                row["transaction_id"],
                row["card_uid"],
                row["action_type"],
                f"{row['amount']:.2f}",
                f"{row['balance_after']:.2f}",
                row["timestamp"]
            ))

    def _on_close(self) -> None:
        """Release background resources on window close."""
        self.nfc_worker.stop()
        self.destroy()

if __name__ == "__main__":
    app = FoodCourtApp()
    app.mainloop()