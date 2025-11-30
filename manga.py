#!/usr/bin/env python3
"""
manga_to_kindle_gui.py
GUI tool to convert image folders / CBZ (zip) / individual images
into device-optimized CBZ volumes with full-height-first scaling with width-fallback (option B).
"""

import os
import zipfile
import tempfile
import threading
from pathlib import Path
from tkinter import Tk, Frame, Button, Listbox, Label, END, filedialog, StringVar, ttk, Text, Scrollbar, VERTICAL, RIGHT, Y, BOTH, Entry
from PIL import Image, ImageEnhance, ImageFilter
from natsort import natsorted

# === Default Target Resolution (fallback) ===
DEFAULT_WIDTH = 1072
DEFAULT_HEIGHT = 1448

# === Device presets ===
DEVICE_PRESETS = {
    "Kindle Basic 11 (1072×1448)": (1072, 1448),
    "Kindle Paperwhite 5 (1236×1648)": (1236, 1648),
    "Kindle Paperwhite 4 (1080×1440)": (1080, 1440),
    "Kindle Oasis 3 (1680×1264)": (1680, 1264),  # note: landscape-ish
    "Kobo Clara HD (1072×1448)": (1072, 1448),
    "Kobo Libra 2 (1264×1680)": (1264, 1680),
    "Boox Generic (1200×1600)": (1200, 1600),
    "Custom...": None
}

# === Helpers ===
def log_to_widget(widget, text):
    widget.configure(state='normal')
    widget.insert(END, text + "\n")
    widget.see("end")
    widget.configure(state='disabled')

def is_image_file(path: Path):
    return path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff')

def extract_images_from_zip(zip_path: Path, extract_to: Path):
    with zipfile.ZipFile(zip_path, 'r') as z:
        members = [m for m in z.namelist() if is_image_file(Path(m))]
        members = natsorted(members)
        # Extract only matched members into extract_to preserving filenames
        for m in members:
            # ensure directories exist
            dest = extract_to / Path(m)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(dest, 'wb') as out:
                out.write(src.read())
        return [extract_to / Path(m) for m in members]

def natural_sorted_images_in_folder(folder: Path):
    imgs = [p for p in folder.iterdir() if p.is_file() and is_image_file(p)]
    return natsorted(imgs)

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def convert_page_to_target(img: Image.Image, target_w=DEFAULT_WIDTH, target_h=DEFAULT_HEIGHT,
                           background=(255,255,255), sharpen_amount=1.0, contrast_amount=1.05,
                           do_sharpen=True, do_contrast=True, jpeg_quality=95):
    """
    Scaling behavior (Option B):
      1) scale by height so page height == target_h
      2) if resulting width > target_w => rescale by width so width == target_w
    This ensures height is preferred but we never overflow horizontally.
    """
    original_w, original_h = img.size

    # convert & ensure RGB
    img = img.convert('RGB')

    # Step 1: scale by height
    scale_h = target_h / original_h
    new_w = int(round(original_w * scale_h))
    new_h = int(round(original_h * scale_h))  # should equal target_h

    # Step 2: if width too big, scale down by width instead
    if new_w > target_w:
        scale_w = target_w / original_w
        new_w = int(round(original_w * scale_w))  # should equal target_w
        new_h = int(round(original_h * scale_w))

    # Perform resize with LANCZOS
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Create background and paste centered (horizontal centering, vertical centering if height < target_h)
    background_image = Image.new('RGB', (target_w, target_h), color=background)
    paste_x = (target_w - new_w) // 2
    paste_y = (target_h - new_h) // 2
    background_image.paste(resized, (paste_x, paste_y))

    # Contrast
    if do_contrast and contrast_amount != 1.0:
        enhancer = ImageEnhance.Contrast(background_image)
        background_image = enhancer.enhance(contrast_amount)

    # Sharpen (UnsharpMask)
    if do_sharpen and sharpen_amount > 0:
        background_image = background_image.filter(ImageFilter.UnsharpMask(radius=1, percent=int(150*sharpen_amount), threshold=3))

    return background_image

def process_volume_source(input_path: Path, output_folder: Path, options: dict, logger=None, progress_callback=None):
    tempdir = Path(tempfile.mkdtemp(prefix="manga_kindle_"))
    try:
        # collect images
        if input_path.is_dir():
            images = natural_sorted_images_in_folder(input_path)
            if logger: log_to_widget(logger, f"Found {len(images)} images in folder.")
            work_images = images
        elif input_path.suffix.lower() in ('.cbz', '.zip'):
            if logger: log_to_widget(logger, f"Extracting {input_path.name}...")
            extracted = extract_images_from_zip(input_path, tempdir)
            if logger: log_to_widget(logger, f"Extracted {len(extracted)} images.")
            work_images = extracted
        elif is_image_file(input_path):
            work_images = [input_path]
        else:
            raise ValueError("Unsupported input type: " + str(input_path))

        if len(work_images) == 0:
            raise ValueError("No images found to process for " + str(input_path))

        processed_files = []
        total = len(work_images)
        for idx, img_path in enumerate(work_images, start=1):
            try:
                if logger: log_to_widget(logger, f"Processing page {idx}/{total}: {img_path.name}")
                with Image.open(img_path) as im:
                    out_im = convert_page_to_target(im,
                                                    target_w=options.get('target_width', DEFAULT_WIDTH),
                                                    target_h=options.get('target_height', DEFAULT_HEIGHT),
                                                    background=options.get('background', (255,255,255)),
                                                    sharpen_amount=options.get('sharpen', 1.0),
                                                    contrast_amount=options.get('contrast', 1.08),
                                                    do_sharpen=options.get('do_sharpen', True),
                                                    do_contrast=options.get('do_contrast', True)
                                                    )
                    out_name = f"{idx:04d}.jpg"
                    out_path = tempdir / out_name
                    out_im.save(out_path, format='JPEG', quality=options.get('jpeg_quality', 92), optimize=True)
                    processed_files.append(out_path)
            except Exception as e:
                if logger: log_to_widget(logger, f"ERROR processing {img_path}: {e}")

            if progress_callback:
                progress_callback(idx / total * 100)

        # Create CBZ
        base_name = input_path.stem
        output_name = f"{base_name} - kindle.cbz"
        output_path = output_folder / output_name
        with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_STORED) as zf:
            for p in processed_files:
                zf.write(p, arcname=p.name)
        if logger: log_to_widget(logger, f"Saved: {output_path}")
        return output_path
    finally:
        if not options.get('keep_temp', False):
            try:
                for p in tempdir.rglob('*'):
                    if p.is_file():
                        p.unlink()
                for d in sorted([d for d in tempdir.rglob('*') if d.is_dir()], reverse=True):
                    try:
                        d.rmdir()
                    except Exception:
                        pass
                tempdir.rmdir()
            except Exception:
                pass

# === GUI ===
class MangaConverterGUI:
    def __init__(self, root):
        self.root = root
        root.title("Manga → Device CBZ Converter (Height-first with width-fallback)")
        self.inputs = []
        self.setup_widgets()

    def setup_widgets(self):
        frm = Frame(self.root)
        frm.pack(fill=BOTH, expand=True, padx=8, pady=8)

        # Top buttons
        btn_frame = Frame(frm)
        btn_frame.pack(fill='x')
        Button(btn_frame, text="Add Files / Folders / CBZ", command=self.add_inputs).pack(side='left', padx=4)
        Button(btn_frame, text="Remove Selected", command=self.remove_selected).pack(side='left', padx=4)
        Button(btn_frame, text="Clear List", command=self.clear_list).pack(side='left', padx=4)

        # Output folder chooser
        out_frame = Frame(frm)
        out_frame.pack(fill='x', pady=(8,0))
        Label(out_frame, text="Output folder:").pack(side='left')
        self.out_var = StringVar(value=str(Path.cwd()))
        Label(out_frame, textvariable=self.out_var).pack(side='left', padx=6)
        Button(out_frame, text="Choose...", command=self.choose_output).pack(side='right')

        # Inputs list
        list_frame = Frame(frm)
        list_frame.pack(fill='both', expand=True, pady=8)
        self.listbox = Listbox(list_frame, selectmode='extended')
        self.listbox.pack(side='left', fill='both', expand=True)
        sb = Scrollbar(list_frame, orient=VERTICAL, command=self.listbox.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.listbox.config(yscrollcommand=sb.set)

        # Settings
        settings_frame = Frame(frm)
        settings_frame.pack(fill='x', pady=(0,8))

        # Device selection
        Label(settings_frame, text="Device model:").grid(row=0, column=0, sticky='w')
        self.device_var = StringVar(value=list(DEVICE_PRESETS.keys())[0])
        device_combo = ttk.Combobox(settings_frame, textvariable=self.device_var, values=list(DEVICE_PRESETS.keys()), state='readonly', width=28)
        device_combo.grid(row=0, column=1, sticky='w', padx=4)
        device_combo.bind("<<ComboboxSelected>>", self.on_device_change)

        # Custom width/height (hidden unless Custom selected)
        Label(settings_frame, text="Width:").grid(row=0, column=2, sticky='e')
        self.custom_w = StringVar(value=str(DEFAULT_WIDTH))
        self.entry_w = Entry(settings_frame, textvariable=self.custom_w, width=7)
        self.entry_w.grid(row=0, column=3, sticky='w', padx=4)

        Label(settings_frame, text="Height:").grid(row=0, column=4, sticky='e')
        self.custom_h = StringVar(value=str(DEFAULT_HEIGHT))
        self.entry_h = Entry(settings_frame, textvariable=self.custom_h, width=7)
        self.entry_h.grid(row=0, column=5, sticky='w', padx=4)

        # Sharpen / Contrast / Background / Keep temp
        Label(settings_frame, text="Sharpen (0.0–2.0):").grid(row=1, column=0, sticky='w')
        self.sharpen = StringVar(value="1.0")
        ttk.Entry(settings_frame, textvariable=self.sharpen, width=6).grid(row=1, column=1, sticky='w', padx=4)

        Label(settings_frame, text="Contrast (1.0–1.5):").grid(row=1, column=2, sticky='w')
        self.contrast = StringVar(value="1.08")
        ttk.Entry(settings_frame, textvariable=self.contrast, width=6).grid(row=1, column=3, sticky='w', padx=4)

        self.bg_choice = StringVar(value='white')
        Label(settings_frame, text="Background:").grid(row=1, column=4, sticky='e')
        ttk.Combobox(settings_frame, textvariable=self.bg_choice, values=['white','black'], width=8).grid(row=1, column=5, sticky='w')

        self.keep_temp = StringVar(value='no')
        ttk.Checkbutton(settings_frame, text="Keep temp files (debug)", variable=self.keep_temp, onvalue='yes', offvalue='no').grid(row=2, column=0, columnspan=2, sticky='w', pady=(6,0))

        # Actions
        action_frame = Frame(frm)
        action_frame.pack(fill='x')
        self.progress = ttk.Progressbar(action_frame, orient='horizontal', length=420, mode='determinate')
        self.progress.pack(side='left', padx=6, pady=6)
        Button(action_frame, text="Start Convert", command=self.start_convert).pack(side='right', padx=6)

        # Log
        self.log = Text(frm, height=12, state='disabled')
        self.log.pack(fill='both', expand=True)

        # Initialize device UI state
        self.on_device_change()

    def on_device_change(self, event=None):
        sel = self.device_var.get()
        if sel == "Custom...":
            self.entry_w.config(state='normal')
            self.entry_h.config(state='normal')
        else:
            preset = DEVICE_PRESETS.get(sel)
            if preset:
                w, h = preset
                self.custom_w.set(str(w))
                self.custom_h.set(str(h))
            self.entry_w.config(state='disabled')
            self.entry_h.config(state='disabled')

    def add_inputs(self):
        choices = filedialog.askopenfilenames(title="Select files or archives (hold ctrl to multi)", filetypes=[("CBZ/ZIP","*.cbz;*.zip"),("Images","*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.tiff"),("All files","*.*")])
        folder = filedialog.askdirectory(title="Optionally pick a folder (click Cancel to skip)")
        for f in choices:
            p = Path(f)
            if str(p) not in self.inputs:
                self.inputs.append(str(p))
                self.listbox.insert(END, str(p))
        if folder:
            if str(folder) not in self.inputs:
                self.inputs.append(str(folder))
                self.listbox.insert(END, str(folder))

    def remove_selected(self):
        selected = list(self.listbox.curselection())
        for i in reversed(selected):
            val = self.listbox.get(i)
            self.inputs.remove(val)
            self.listbox.delete(i)

    def clear_list(self):
        self.inputs.clear()
        self.listbox.delete(0, END)

    def choose_output(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d:
            self.out_var.set(d)

    def start_convert(self):
        if not self.inputs:
            log_to_widget(self.log, "No inputs selected.")
            return
        out_folder = Path(self.out_var.get())
        ensure_dir(out_folder)

        try:
            target_w = int(self.custom_w.get())
            target_h = int(self.custom_h.get())
        except Exception as e:
            log_to_widget(self.log, f"Invalid custom width/height: {e}")
            return

        options = {
            'target_width': target_w,
            'target_height': target_h,
            'background': (255,255,255) if self.bg_choice.get() == 'white' else (0,0,0),
            'sharpen': float(self.sharpen.get()),
            'contrast': float(self.contrast.get()),
            'do_sharpen': True,
            'do_contrast': True,
            'jpeg_quality': 92,
            'keep_temp': (self.keep_temp.get() == 'yes')
        }

        worker = threading.Thread(target=self._run_batch, args=(list(self.inputs), out_folder, options))
        worker.daemon = True
        worker.start()

    def _run_batch(self, inputs, out_folder, options):
        self.progress['value'] = 0
        n = len(inputs)
        for i, s in enumerate(inputs, start=1):
            p = Path(s)
            log_to_widget(self.log, f"=== Processing {p.name} ({i}/{n}) ===")
            def update_progress(percent):
                overall = ((i-1)/n)*100 + percent / n
                self.progress['value'] = overall
            try:
                output = process_volume_source(p, out_folder, options, logger=self.log, progress_callback=update_progress)
                log_to_widget(self.log, f"Done: {output}")
            except Exception as e:
                log_to_widget(self.log, f"ERROR processing {p}: {e}")
        self.progress['value'] = 100
        log_to_widget(self.log, "All done.")

def main():
    root = Tk()
    app = MangaConverterGUI(root)
    root.geometry("900x600")
    root.mainloop()

if __name__ == '__main__':
    main()
