"""Simple Tkinter GUI for revtag."""

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import Options, run


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rev Tag 자동 표시")
        self.geometry("760x560")
        self.sample = tk.StringVar()
        self.excel = tk.StringVar()
        self.out = tk.StringVar()
        self.order = tk.StringVar(value="rows")
        self.detect = tk.StringVar(value="raster")
        self.cloudy_only = tk.BooleanVar(value=False)
        self.inputs: list[str] = []

        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        def row(r, label, var, cmd):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(f, textvariable=var).grid(row=r, column=1, sticky="ew", padx=5)
            ttk.Button(f, text="찾기...", command=cmd).grid(row=r, column=2)

        row(0, "SAMPLE PDF (태그 주석)", self.sample,
            lambda: self.sample.set(filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")]) or self.sample.get()))
        row(1, "엑셀 리스트 (ISO / XX_YY)", self.excel,
            lambda: self.excel.set(filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xlsm")]) or self.excel.get()))
        row(2, "결과 저장 폴더", self.out,
            lambda: self.out.set(filedialog.askdirectory() or self.out.get()))

        ttk.Label(f, text="ISO PDF").grid(row=3, column=0, sticky="nw", pady=3)
        self.lst = tk.Listbox(f, height=6)
        self.lst.grid(row=3, column=1, sticky="nsew", padx=5)
        bf = ttk.Frame(f)
        bf.grid(row=3, column=2, sticky="n")
        ttk.Button(bf, text="파일 추가", command=self.add_files).pack(fill="x")
        ttk.Button(bf, text="폴더 추가", command=self.add_dir).pack(fill="x", pady=2)
        ttk.Button(bf, text="비우기", command=self.clear).pack(fill="x")

        of = ttk.LabelFrame(f, text="옵션", padding=6)
        of.grid(row=4, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(of, text="ZZ 순서").grid(row=0, column=0, sticky="w")
        ttk.Combobox(of, textvariable=self.order, state="readonly", width=40,
                     values=["rows", "cols", "annot"]).grid(row=0, column=1, sticky="w")
        ttk.Label(of, text="rows=위→아래,왼→오 / cols=왼→오,위→아래 / annot=주석순").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Label(of, text="cloud 검출").grid(row=1, column=0, sticky="w")
        ttk.Combobox(of, textvariable=self.detect, state="readonly", width=40,
                     values=["raster", "annot", "auto"]).grid(row=1, column=1, sticky="w")
        ttk.Label(of, text="raster=빨간색으로 검출 / annot=PDF 주석").grid(row=1, column=2, sticky="w", padx=6)
        ttk.Checkbutton(of, text="구름(cloudy) 테두리 주석만", variable=self.cloudy_only).grid(row=2, column=1, sticky="w")

        self.btn = ttk.Button(f, text="실행", command=self.start)
        self.btn.grid(row=5, column=0, columnspan=3, pady=4)
        self.log = tk.Text(f, height=12)
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew")
        f.rowconfigure(6, weight=1)

    def add_files(self):
        for p in filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf")]):
            self.inputs.append(p)
            self.lst.insert("end", p)

    def add_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.inputs.append(d)
            self.lst.insert("end", d + "  (폴더)")

    def clear(self):
        self.inputs.clear()
        self.lst.delete(0, "end")

    def write(self, msg):
        self.after(0, lambda: (self.log.insert("end", msg + "\n"), self.log.see("end")))

    def start(self):
        if not (self.sample.get() and self.excel.get() and self.out.get() and self.inputs):
            messagebox.showwarning("입력 필요", "SAMPLE PDF, 엑셀, 결과 폴더, ISO PDF를 모두 지정하세요.")
            return
        opts = Options(order=self.order.get(), detect=self.detect.get(), require_cloudy=self.cloudy_only.get())
        self.btn.config(state="disabled")

        def work():
            try:
                run(self.sample.get(), self.excel.get(), list(self.inputs), self.out.get(), opts, log=self.write)
            except Exception as e:
                self.write(f"[error] {e}")
            finally:
                self.after(0, lambda: self.btn.config(state="normal"))

        threading.Thread(target=work, daemon=True).start()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
