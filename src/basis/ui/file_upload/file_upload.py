import asyncio
import base64
import math
import os
import uuid
from pathlib import Path
from basis.shared.component import Component, IS_CLIENT
from basis.shared.reactive import computed
from basis.shared.actions import server_action

if IS_CLIENT:
    from pyscript import window, document, ffi
else:
    window = document = ffi = None


class FileUpload(Component):
    """
    A premium, reactive file upload component with drag-and-drop support,
    real-time progress bar, and server-side chunked append logic.

    Attributes:
        multiple       : Whether to support multiple files ("true" | "false").
        accept         : Allowed file types, e.g. "image/*,application/pdf" (default: "*/*").
        disabled       : Disables interactions ("" | "true").
        auto_upload    : Whether to upload immediately on selection ("true" | "false").
        show_progress  : Whether to show progress bars ("true" | "false").
        max_size_mb    : Max size allowed per file in MB (default: 10).
        label          : Primary title text in dropzone (default: "Upload Files").
        description    : Subtitle description text in dropzone.
    """
    __tag__ = "ui-file-upload"

    multiple = "false"
    accept = "*/*"
    disabled = ""
    auto_upload = "true"
    show_progress = "true"
    max_size_mb = "10"
    label = "Upload Files"
    description = "Drag & drop files here or click to browse"

    # Reactive states
    files = []
    dragging = False

    def __init__(self):
        super().__init__()
        self.files = []
        self.dragging = False

    @computed(dependencies=["disabled"])
    def disabled_attr(self):
        return "disabled" if self.is_disabled() else ""

    @computed(dependencies=["multiple"])
    def multiple_attr(self):
        return "multiple" if self.multiple_enabled() else ""

    def is_disabled(self):
        return str(self.disabled).lower() == "true" or self.disabled is True

    def multiple_enabled(self):
        return str(self.multiple).lower() == "true" or self.multiple is True

    def is_progress_enabled(self):
        return str(self.show_progress).lower() == "true" or self.show_progress is True

    # ── Drag & Drop Event Handlers ───────────────────────────────────

    def on_dragover(self, event):
        event.preventDefault()
        if self.is_disabled():
            return
        event.dataTransfer.dropEffect = "copy"
        self.dragging = True

    def on_dragleave(self, event):
        event.preventDefault()
        self.dragging = False

    def on_drop(self, event):
        event.preventDefault()
        self.dragging = False
        if self.is_disabled():
            return
        dt = event.dataTransfer
        if dt and dt.files:
            self.handle_files(dt.files)

    def on_change(self, event):
        event.stopPropagation()
        if self.is_disabled():
            return
        files = event.target.files
        if files:
            self.handle_files(files)

    def trigger_select(self, event):
        if self.is_disabled():
            return
        # Avoid triggering select dialogue when clicking the remove button
        target = event.target
        curr = target
        while curr:
            if hasattr(curr, "classList") and curr.classList.contains("ui-upload-file-remove"):
                return
            curr = curr.parentNode

        file_input = self.__element__.querySelector(".ui-upload-input")
        if file_input:
            file_input.click()

    def on_remove_file(self, event):
        target = event.target
        file_id = None
        curr = target
        while curr:
            if hasattr(curr, "getAttribute") and curr.getAttribute("data-id"):
                file_id = curr.getAttribute("data-id")
                break
            curr = curr.parentNode

        if file_id:
            self.files = [f for f in self.files if f["id"] != file_id]
            self.dispatch_change_event()

    # ── Validation & Chunked Upload ──────────────────────────────────

    def validate_file_client(self, name, size, mime_type):
        """Validates file constraints on the client side."""
        # 1. Size check
        try:
            max_size_bytes = float(self.max_size_mb) * 1024 * 1024
        except ValueError:
            max_size_bytes = 10 * 1024 * 1024

        if size > max_size_bytes:
            return False, f"File exceeds size limit of {self.max_size_mb}MB"

        # 2. Extension / accept check
        accept_rules = str(self.accept).strip()
        if not accept_rules or accept_rules in ["*", "*/*"]:
            return True, ""

        rules = [r.strip().lower() for r in accept_rules.split(",")]
        name_lower = name.lower()
        mime_lower = mime_type.lower() if mime_type else ""

        matched = False
        for rule in rules:
            if rule.startswith("."):
                if name_lower.endswith(rule):
                    matched = True
                    break
            elif "/" in rule:
                if rule.endswith("/*"):
                    prefix = rule.split("/*")[0]
                    if mime_lower.startswith(prefix):
                        matched = True
                        break
                elif mime_lower == rule:
                    matched = True
                    break

        if not matched:
            return False, f"Invalid file type. Allowed: {self.accept}"
        return True, ""

    def handle_files(self, js_files):
        new_files_list = list(self.files)
        is_multiple = self.multiple_enabled()

        if not is_multiple:
            new_files_list = []

        for idx in range(js_files.length):
            file = js_files.item(idx)
            file_id = str(uuid.uuid4())

            valid, error_msg = self.validate_file_client(file.name, file.size, file.type)

            # Format file size nicely
            if file.size >= 1024 * 1024:
                formatted_size = f"{file.size / (1024 * 1024):.2f} MB"
            else:
                formatted_size = f"{file.size / 1024:.1f} KB"

            file_info = {
                "id": file_id,
                "name": file.name,
                "size": file.size,
                "formatted_size": formatted_size,
                "type": file.type or "application/octet-stream",
                "status": "pending" if valid else "error",
                "progress": 0,
                "error_msg": error_msg,
                "file_path": ""
            }
            new_files_list.append(file_info)

            if not is_multiple:
                break

        self.files = new_files_list

        # If auto upload is enabled, trigger upload for pending files
        if str(self.auto_upload).lower() == "true":
            for file_info in self.files:
                if file_info["status"] == "pending":
                    # Locate matching file in jsFileList
                    for idx in range(js_files.length):
                        f = js_files.item(idx)
                        if f.name == file_info["name"] and f.size == file_info["size"]:
                            asyncio.create_task(self.upload_file_async(file_info["id"], f))
                            break
        else:
            # If auto_upload is disabled, mark valid pending files as success locally
            new_files = []
            for file_info in self.files:
                if file_info["status"] == "pending":
                    new_files.append({**file_info, "status": "success", "progress": 100})
                else:
                    new_files.append(file_info)
            self.files = new_files
            self.dispatch_change_event()

    def update_file_state(self, file_id, **updates):
        new_files = []
        for f in self.files:
            if f["id"] == file_id:
                new_files.append({**f, **updates})
            else:
                new_files.append(f)
        self.files = new_files

    async def upload_file_async(self, file_id, js_file):
        file_info = None
        for f in self.files:
            if f["id"] == file_id:
                file_info = f
                break
        if not file_info:
            return

        self.update_file_state(file_id, status="uploading", progress=0)

        chunk_size = 500 * 1024  # 500 KB
        file_size = js_file.size
        total_chunks = math.ceil(file_size / chunk_size) if file_size > 0 else 1

        from basis.client.actions import call_action

        try:
            for chunk_idx in range(total_chunks):
                start = chunk_idx * chunk_size
                end = min(start + chunk_size, file_size)

                blob = js_file.slice(start, end)

                future = asyncio.get_event_loop().create_future()
                reader = window.FileReader.new()

                def onloadend(e):
                    future.set_result(reader.result)

                onloadend_proxy = ffi.create_proxy(onloadend)
                reader.onloadend = onloadend_proxy
                reader.readAsDataURL(blob)

                try:
                    data_url = await future
                finally:
                    onloadend_proxy.destroy()

                base64_data = data_url.split(",")[1] if "," in data_url else data_url

                # Call backend action with verification parameters
                res = await call_action(
                    "basis.ui.file_upload.file_upload.save_upload_chunk",
                    None,
                    file_id,
                    js_file.name,
                    file_size,
                    js_file.type or "application/octet-stream",
                    chunk_idx,
                    total_chunks,
                    base64_data,
                    self.accept,
                    self.max_size_mb
                )

                if res and res.get("success"):
                    self.update_file_state(file_id, progress=int((chunk_idx + 1) / total_chunks * 100))
                else:
                    error_msg = res.get("error", "Chunk upload failed") if res else "Server connection error"
                    self.update_file_state(file_id, status="error", error_msg=error_msg)
                    self.dispatch_change_event()
                    return

            # Successfully uploaded all chunks
            self.update_file_state(file_id, status="success", file_path=res.get("file_path", ""))

            # Get the updated file_info to dispatch
            updated_file_info = None
            for f in self.files:
                if f["id"] == file_id:
                    updated_file_info = f
                    break

            # Trigger custom event on upload success
            if IS_CLIENT and updated_file_info:
                self.__element__.dispatchEvent(window.CustomEvent.new(
                    "upload-success",
                    ffi.to_js({"detail": {"file": updated_file_info}, "bubbles": True})
                ))

            self.dispatch_change_event()

        except Exception as e:
            self.update_file_state(file_id, status="error", error_msg=str(e))
            self.dispatch_change_event()

    def dispatch_change_event(self):
        if IS_CLIENT:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "change",
                ffi.to_js({"detail": {"files": self.files}, "bubbles": True})
            ))

    # ── Styling & Markup ─────────────────────────────────────────────

    def style(self):
        """
        /* ── Main Container ────────────────────────────────── */
        ui-file-upload {
            display: block;
            width: 100%;
        }

        .ui-upload-container {
            display: flex;
            flex-direction: column;
            gap: 1rem;
            width: 100%;
            font-family: inherit;
        }

        /* ── Dropzone Area ──────────────────────────────────── */
        .ui-upload-dropzone {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 2.25rem 1.5rem;
            border: 2px dashed var(--border-color, rgba(255, 255, 255, 0.15));
            border-radius: 0.75rem;
            background: var(--bg-secondary, rgba(30, 41, 59, 0.4));
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            text-align: center;
            user-select: none;
        }

        .ui-upload-dropzone:hover:not(.disabled) {
            border-color: var(--accent-color, #3b82f6);
            background: rgba(59, 130, 246, 0.05);
            transform: scale(1.005);
        }

        .ui-upload-dropzone.ui-upload-dragging:not(.disabled) {
            border-color: var(--accent-color, #3b82f6);
            background: rgba(59, 130, 246, 0.08);
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.15);
        }

        .ui-upload-dropzone.disabled {
            opacity: 0.55;
            cursor: not-allowed;
            background: rgba(0, 0, 0, 0.05);
        }

        /* ── Upload Icon ───────────────────────────────────── */
        .ui-upload-icon {
            width: 42px;
            height: 42px;
            color: var(--text-secondary, #94a3b8);
            margin-bottom: 0.85rem;
            transition: transform 0.2s ease;
        }

        .ui-upload-dropzone:hover:not(.disabled) .ui-upload-icon {
            transform: translateY(-2px);
            color: var(--accent-color, #3b82f6);
        }

        /* ── Dropzone Text ──────────────────────────────────── */
        .ui-upload-title {
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--text-primary, #f8fafc);
            margin-bottom: 0.25rem;
        }

        .ui-upload-desc {
            font-size: 0.8rem;
            color: var(--text-secondary, #94a3b8);
        }

        /* ── File List ──────────────────────────────────────── */
        .ui-upload-file-list {
            display: flex;
            flex-direction: column;
            gap: 0.65rem;
            margin-top: 0.5rem;
        }

        .ui-upload-file-card {
            display: grid;
            grid-template-columns: auto 1fr auto;
            align-items: center;
            gap: 0.85rem;
            padding: 0.75rem 1rem;
            background: var(--bg-secondary, rgba(30, 41, 59, 0.3));
            border: 1px solid var(--border-color, rgba(255, 255, 255, 0.06));
            border-radius: 0.65rem;
            animation: ui-upload-slide-in 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            position: relative;
            overflow: hidden;
        }

        @keyframes ui-upload-slide-in {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* ── File Icons / Info ──────────────────────────────── */
        .ui-upload-file-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 34px;
            height: 34px;
            background: rgba(255, 255, 255, 0.04);
            border-radius: 0.45rem;
            color: var(--text-secondary, #94a3b8);
        }

        .ui-upload-file-info {
            display: flex;
            flex-direction: column;
            min-width: 0; /* truncate text handles */
        }

        .ui-upload-file-name {
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-primary, #f8fafc);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .ui-upload-file-meta {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.75rem;
            margin-top: 0.15rem;
        }

        .ui-upload-file-size {
            color: var(--text-secondary, #64748b);
        }

        .ui-upload-file-status-text {
            color: var(--accent-color, #3b82f6);
            font-weight: 500;
            text-transform: capitalize;
        }

        .ui-upload-file-status-text.status-error {
            color: #ef4444;
        }

        /* ── Remove Button ──────────────────────────────────── */
        .ui-upload-file-remove {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 26px;
            height: 26px;
            border-radius: 50%;
            border: none;
            background: transparent;
            color: var(--text-secondary, #94a3b8);
            cursor: pointer;
            transition: all 0.2s ease;
            z-index: 5;
        }

        .ui-upload-file-remove:hover {
            background: rgba(239, 68, 68, 0.15);
            color: #ef4444;
            transform: scale(1.05);
        }

        /* ── Progress Indicators ────────────────────────────── */
        .ui-upload-progress-wrapper {
            grid-column: 1 / span 3;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-top: 0.4rem;
        }

        .ui-upload-progress-bg {
            flex: 1;
            height: 4px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 2px;
            overflow: hidden;
            position: relative;
        }

        .ui-upload-progress-bar {
            height: 100%;
            background: linear-gradient(90deg, var(--accent-color, #3b82f6) 0%, #8b5cf6 100%);
            border-radius: 2px;
            transition: width 0.15s ease-out;
        }

        .ui-upload-progress-pct {
            font-size: 0.725rem;
            font-family: monospace;
            color: var(--text-secondary, #94a3b8);
            min-width: 28px;
            text-align: right;
        }
        """

    def template(self):
        """
        <div class="ui-upload-container">
            <div 
                class="ui-upload-dropzone {dragging and 'ui-upload-dragging' or ''} {disabled_attr}"
                onclick="{trigger_select}"
                ondragover="{on_dragover}"
                ondragleave="{on_dragleave}"
                ondrop="{on_drop}">
                
                <input 
                    class="ui-upload-input" 
                    type="file" 
                    {multiple_attr} 
                    accept="{accept}"
                    {disabled_attr}
                    onchange="{on_change}" 
                    style="display: none;" />
                    
                <svg class="ui-upload-icon" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                
                <span class="ui-upload-title">{label}</span>
                <span class="ui-upload-desc">{description}</span>
            </div>
            
            <div class="ui-upload-file-list" if="{files}">
                <div class="ui-upload-file-card" for="f" in="{files}" key="id" data-id="{f['id']}">
                    <div class="ui-upload-file-icon">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" width="18" height="18">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                    </div>
                    
                    <div class="ui-upload-file-info">
                        <span class="ui-upload-file-name">{f['name']}</span>
                        <div class="ui-upload-file-meta">
                            <span class="ui-upload-file-size">{f['formatted_size']}</span>
                            <span class="ui-upload-file-status-text {f['status'] == 'error' and 'status-error' or ''}">{f['error_msg'] or f['status']}</span>
                        </div>
                    </div>
                    
                    <button class="ui-upload-file-remove" onclick="{on_remove_file}">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                    
                    <div class="ui-upload-progress-wrapper" if="{show_progress and f['status'] == 'uploading'}">
                        <div class="ui-upload-progress-bg">
                            <div class="ui-upload-progress-bar" style="width: {f['progress']}%"></div>
                        </div>
                        <span class="ui-upload-progress-pct">{f['progress']}%</span>
                    </div>
                </div>
            </div>
        </div>
        """


# ── Server Actions (RPC Endpoint Methods) ───────────────────────────

@server_action
def save_upload_chunk(
    upload_id: str,
    filename: str,
    file_size: int,
    content_type: str,
    chunk_index: int,
    total_chunks: int,
    base64_data: str,
    accept: str,
    max_size_mb: str
) -> dict:
    """
    Sequentially appends upload chunks to uploads/files/<upload_id>/<filename>.incomplete.
    Performs server-side validation on file size and extension rules.
    Removes the .incomplete extension once the final chunk completes.
    """
    try:
        # 1. Server validation (both size and extension check)
        try:
            max_size_bytes = float(max_size_mb) * 1024 * 1024
        except ValueError:
            max_size_bytes = 10 * 1024 * 1024

        if file_size > max_size_bytes:
            return {"success": False, "error": f"File size exceeds limit of {max_size_mb}MB"}

        accept = accept.strip()
        if accept and accept not in ["*", "*/*"]:
            rules = [r.strip().lower() for r in accept.split(",")]
            name_lower = filename.lower()
            mime_lower = content_type.lower()
            matched = False
            for rule in rules:
                if rule.startswith("."):
                    if name_lower.endswith(rule):
                        matched = True
                        break
                elif "/" in rule:
                    if rule.endswith("/*"):
                        prefix = rule.split("/*")[0]
                        if mime_lower.startswith(prefix):
                            matched = True
                            break
                    elif mime_lower == rule:
                        matched = True
                        break
            if not matched:
                return {"success": False, "error": f"Invalid file type. Allowed: {accept}"}

        # 2. Setup directory
        UPLOAD_DIR = Path("uploads/files")
        upload_dir = UPLOAD_DIR / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        incomplete_file = upload_dir / f"{filename}.incomplete"
        final_file = upload_dir / filename

        # Decode base64 bytes
        chunk_bytes = base64.b64decode(base64_data)

        # Open in append binary mode (first chunk creates/truncates, subsequent append)
        mode = "wb" if chunk_index == 0 else "ab"
        with open(incomplete_file, mode) as f:
            f.write(chunk_bytes)

        # If it is the last chunk, rename to remove the `.incomplete` suffix
        if chunk_index + 1 == total_chunks:
            if final_file.exists():
                final_file.unlink()  # delete existing file
            incomplete_file.rename(final_file)
            print(f"[FileUpload Server] Completed upload: {final_file} (size: {file_size} bytes)")
            return {
                "success": True,
                "file_path": str(final_file),
                "filename": filename,
                "upload_id": upload_id
            }

        return {
            "success": True,
            "upload_id": upload_id,
            "chunk_index": chunk_index
        }

    except Exception as e:
        print(f"[FileUpload Server] Error saving chunk {chunk_index} for upload {upload_id}: {e}")
        return {
            "success": False,
            "error": str(e)
        }
