import asyncio
import base64
import os
import uuid
from pathlib import Path
from basis.shared.component import Component, IS_CLIENT
from basis.shared.dag import computed
from basis.shared.actions import server_action

if IS_CLIENT:
    from pyscript import window, document, ffi
else:
    window = document = ffi = None

# Default upload directory on the server
UPLOAD_DIR = Path("uploads/audio")


class AudioRecorder(Component):
    """
    A premium, reactive audio recorder component with local IndexedDB caching,
    real-time canvas visualization, and server-side chunk assembly.

    Attributes:
        interval_ms    : Time slice interval to capture and send audio chunks (default: 2000).
        visualizer     : Whether to show the real-time audio wave visualizer ("true" | "false").
        save_to_server : Whether to automatically send chunks to the backend ("true" | "false").
        cache_locally  : Whether to cache chunks locally in the browser's IndexedDB ("true" | "false").
        disabled       : Disables interactions ("" | "true").
    """
    __tag__ = "ui-audio-recorder"

    interval_ms = 2000
    visualizer = "true"
    save_to_server = "true"
    cache_locally = "true"
    disabled = ""

    # Reactive UI states
    recording = False
    status_text = "Click to record"
    formatted_time = "00:00"

    def __init__(self):
        super().__init__()
        self.media_recorder = None
        self.stream = None
        self.chunk_index = 0
        self.current_session_id = None
        self.seconds_elapsed = 0
        self.db = None

        # Track pending async chunk uploads so we can wait for them before combining
        self._pending_chunks = 0

        # Web Audio Nodes for visualizer
        self.audio_ctx = None
        self.analyser = None
        self.data_array = None
        self.animation_id = None

        # Event listeners and proxies
        self._ondataavailable_proxy = None
        self._onstop_proxy = None
        self._visualizer_proxy = None

    @computed(dependencies=["disabled"])
    def disabled_attr(self):
        if str(self.disabled).lower() == "true" or self.disabled is True:
            return "disabled"
        return ""

    @computed(dependencies=["visualizer"])
    def visualizer_enabled(self):
        return str(self.visualizer).lower() == "true" or self.visualizer is True

    @computed(dependencies=["recording"])
    def show_meta(self):
        return True

    # ── IndexedDB Caching ───────────────────────────────────────────
    
    async def _init_db(self):
        """Initializes the browser's IndexedDB for caching audio chunks."""
        if not IS_CLIENT:
            return None
            
        future = asyncio.get_event_loop().create_future()
        
        request = window.indexedDB.open("audio_recorder_db", 1)
        
        def on_success(event):
            self.db = event.target.result
            self._cleanup_db_open_proxies()
            future.set_result(self.db)
            
        def on_error(event):
            self._cleanup_db_open_proxies()
            future.set_exception(Exception("Failed to open IndexedDB"))
            
        def on_upgrade(event):
            db = event.target.result
            if not db.objectStoreNames.contains("chunks"):
                db.createObjectStore("chunks")
                
        self._db_success_proxy = ffi.create_proxy(on_success)
        self._db_error_proxy = ffi.create_proxy(on_error)
        self._db_upgrade_proxy = ffi.create_proxy(on_upgrade)
        
        request.onsuccess = self._db_success_proxy
        request.onerror = self._db_error_proxy
        request.onupgradeneeded = self._db_upgrade_proxy
        
        return await future

    def _cleanup_db_open_proxies(self):
        if hasattr(self, "_db_success_proxy") and self._db_success_proxy:
            #self._db_success_proxy.destroy()
            self.__dict__['_db_success_proxy'] = None
        if hasattr(self, "_db_error_proxy") and self._db_error_proxy:
            #self._db_error_proxy.destroy()
            self.__dict__['_db_error_proxy'] = None
        if hasattr(self, "_db_upgrade_proxy") and self._db_upgrade_proxy:
            #self._db_upgrade_proxy.destroy()
            self.__dict__['_db_upgrade_proxy'] = None

    async def _cache_chunk_locally(self, session_id, index, blob):
        """Saves an audio chunk Blob to IndexedDB."""
        if not self.db:
            await self._init_db()
            
        future = asyncio.get_event_loop().create_future()
        
        transaction = self.db.transaction(ffi.to_js(["chunks"]), "readwrite")
        store = transaction.objectStore("chunks")
        key = f"{session_id}:{index}"
        
        request = store.put(blob, key)
        
        def on_success(event):
            #self._put_success_proxy.destroy()
            #self._put_error_proxy.destroy()
            future.set_result(True)
            
        def on_error(event):
            #self._put_success_proxy.destroy()
            #self._put_error_proxy.destroy()
            future.set_result(False)
            
        self._put_success_proxy = ffi.create_proxy(on_success)
        self._put_error_proxy = ffi.create_proxy(on_error)
        
        request.onsuccess = self._put_success_proxy
        request.onerror = self._put_error_proxy
        
        await future

    async def _clear_local_cache(self, session_id):
        """Clears all cached chunks for this session from IndexedDB."""
        if not self.db:
            await self._init_db()
            
        future = asyncio.get_event_loop().create_future()
        
        transaction = self.db.transaction(ffi.to_js(["chunks"]), "readwrite")
        store = transaction.objectStore("chunks")
        
        lower_bound = f"{session_id}:"
        upper_bound = f"{session_id}:\uffff"
        key_range = window.IDBKeyRange.bound(lower_bound, upper_bound)
        
        request = store.delete(key_range)
        
        def on_success(event):
            #self._del_success_proxy.destroy()
            #self._del_error_proxy.destroy()
            future.set_result(True)
            
        def on_error(event):
            #self._del_success_proxy.destroy()
            #self._del_error_proxy.destroy()
            future.set_result(False)
            
        self._del_success_proxy = ffi.create_proxy(on_success)
        self._del_error_proxy = ffi.create_proxy(on_error)
        
        request.onsuccess = self._del_success_proxy
        request.onerror = self._del_error_proxy
        
        await future

    # ── Client-side Recording Flow ───────────────────────────────────

    def toggle_recording(self, event):
        
        """Triggers starting or stopping of the recording."""
        if self.status_text in ["Starting...", "Stopping...", "Merging audio..."]:
            return
            
        if self.recording:
            self.status_text = "Stopping..."
            asyncio.create_task(self.stop_recording())
        else:
            self.status_text = "Starting..."
            asyncio.create_task(self.start_recording())

    async def start_recording(self):
        """Requests mic permission and starts the MediaRecorder."""
        if not IS_CLIENT:
            return

        try:
            self.status_text = "Connecting microphone..."
            media_config = ffi.to_js({"audio": True})
            self.stream = await window.navigator.mediaDevices.getUserMedia(media_config)
            
            # Setup session
            self.chunk_index = 0
            self._pending_chunks = 0
            self.current_session_id = str(uuid.uuid4())
            self.seconds_elapsed = 0
            self.formatted_time = "00:00"
            
            # Prepare IndexedDB database
            if str(self.cache_locally).lower() == "true":
                await self._init_db()
            
            # Initialize MediaRecorder
            self.media_recorder = window.MediaRecorder.new(self.stream)

            self._ondataavailable_proxy = ffi.create_proxy(self.on_data_available)
            self.media_recorder.ondataavailable = self._ondataavailable_proxy
            
            self._onstop_proxy = ffi.create_proxy(self.on_recorder_stop)
            self.media_recorder.onstop = self._onstop_proxy
            
            # Initialize Visualizer
            if self.visualizer_enabled:
                self.start_visualizer()

            # Start MediaRecorder with user interval
            self.media_recorder.start(int(self.interval_ms))
            # Use the reactive setter so the UI re-renders
            self.recording = True
            self.status_text = "Recording..."
            
            # Start Timer
            asyncio.create_task(self.start_timer_loop())

            # Dispatch event
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "recording-start", 
                ffi.to_js({"detail": {"session_id": self.current_session_id}, "bubbles": True})
            ))
            
        except Exception as e:
            self.status_text = f"Error: {str(e)}"
            self.recording = False
            self.cleanup()

    def on_data_available(self, event):
        """Callback triggered when an audio chunk is available."""
        if not event.data or event.data.size == 0:
            return
            
        chunk_idx = self.chunk_index
        self.chunk_index += 1
        
        # Cache chunk locally in IndexedDB if enabled
        if str(self.cache_locally).lower() == "true":
            asyncio.create_task(self._cache_chunk_locally(self.current_session_id, chunk_idx, event.data))
            
        # Send chunk to server if enabled
        if str(self.save_to_server).lower() == "true":
            # Count this upload as pending so finish_recording can wait for it
            self._pending_chunks += 1
            
            # FileReader to convert Blob -> base64
            reader = window.FileReader.new()
            
            # Capture blob data/type synchronously before the async boundary
            blob_type = event.data.type or "audio/webm"
            
            def onloadend(e):
                data_url = reader.result
                base64_data = data_url.split(",")[1] if "," in data_url else data_url
                asyncio.create_task(self.send_chunk(base64_data, chunk_idx, blob_type))
                
            onloadend_proxy = ffi.create_proxy(onloadend)
            reader.onloadend = onloadend_proxy
            reader.readAsDataURL(event.data)
        else:
            # If not sending to server, just dispatch custom client event
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "chunk",
                ffi.to_js({
                    "detail": {
                        "index": chunk_idx,
                        "session_id": self.current_session_id,
                        "local_cached": True
                    },
                    "bubbles": True
                })
            ))

    async def send_chunk(self, base64_data, index, content_type):
        """Sends the chunk to the server action and dispatches standard event."""
        session_id = self.current_session_id
        
        # Dispatch Custom event
        self.__element__.dispatchEvent(window.CustomEvent.new(
            "chunk", 
            ffi.to_js({
                "detail": {
                    "chunk": base64_data,
                    "index": index,
                    "session_id": session_id,
                    "content_type": content_type
                },
                "bubbles": True
            })
        ))
        
        try:
            from basis.client.actions import call_server_action
            path = "basis.ui.audio_recorder.audio_recorder.save_audio_chunk"
            
            res = await call_server_action(path, None, session_id, index, base64_data, content_type)
            if res and res.get("success"):
                if self.recording:
                    self.status_text = "Recording..."
            else:
                self.status_text = f"Upload error: {res.get('error', 'unknown')}"
        except Exception as e:
            self.status_text = f"Upload failed: {str(e)}"
        finally:
            # Decrement pending count regardless of success/failure
            self._pending_chunks = max(0, self._pending_chunks - 1)

    async def stop_recording(self):
        """Stops MediaRecorder capturing."""
        if not self.recording or not self.media_recorder:
            return
            
        self.status_text = "Stopping..."
        self.media_recorder.stop()

    def on_recorder_stop(self, event):
        """Triggered once the media recorder has fully stopped."""
        asyncio.create_task(self.finish_recording())

    async def finish_recording(self):
        """Finalizes the recording, waits for pending uploads, then combines on server."""
        session_id = self.current_session_id
        total_chunks = self.chunk_index
        
        # Mark as no longer recording immediately so the UI updates
        self.recording = False

        # Dispatch recording-stop
        self.__element__.dispatchEvent(window.CustomEvent.new(
            "recording-stop", 
            ffi.to_js({
                "detail": {
                    "session_id": session_id,
                    "total_chunks": total_chunks
                },
                "bubbles": True
            })
        ))
        
        if str(self.save_to_server).lower() == "true":
            self.status_text = "Uploading..."

            # Brief initial delay: in PyScript's JS-to-Python event bridge the
            # final `ondataavailable` (fired by stop()) can arrive *after* onstop.
            # Waiting here lets that event fire and increment _pending_chunks
            # before we start polling it.
            await asyncio.sleep(0.6)

            # Now wait for all in-flight chunk uploads to finish before combining.
            wait_attempts = 0
            while self._pending_chunks > 0 and wait_attempts < 50:
                await asyncio.sleep(0.2)
                wait_attempts += 1

            self.status_text = "Merging audio..."
            try:
                from basis.client.actions import call_server_action
                path = "basis.ui.audio_recorder.audio_recorder.combine_audio_chunks"

                res = await call_server_action(path, None, session_id)
                if res and res.get("success"):
                    file_path = res.get("file_path")
                    self.status_text = "Saved!"
                    
                    # Clear local IndexedDB cache on success
                    if str(self.cache_locally).lower() == "true":
                        await self._clear_local_cache(session_id)
                    
                    # Dispatch recording-saved
                    self.__element__.dispatchEvent(window.CustomEvent.new(
                        "recording-saved",
                        ffi.to_js({
                            "detail": {
                                "session_id": session_id,
                                "file_path": file_path
                            },
                            "bubbles": True
                        })
                    ))
                else:
                    self.status_text = f"Merge error: {res.get('error', 'unknown')}"
            except Exception as e:
                self.status_text = f"Merge failed: {str(e)}"
        else:
            self.status_text = "Saved locally"
            
        self.cleanup()

    def cleanup(self):
        """Stops tracks, animation frames, and releases event proxies."""

        # Use reactive setter so the UI always reflects the stopped state
        self.recording = False
        self._pending_chunks = 0
        
        if self.stream:
            try:
                tracks = self.stream.getTracks()
                for i in range(tracks.length):
                    tracks.getItem(i).stop()
            except Exception:
                pass
            self.__dict__["stream"] = None
            
        if self.animation_id:
            try:
                window.cancelAnimationFrame(self.animation_id)
            except Exception:
                pass
            self.animation_id = None
            
        if self._ondataavailable_proxy:
            #self._ondataavailable_proxy.destroy()
            self.__dict__["_ondataavailable_proxy"] = None
        if self._onstop_proxy:
            #self._onstop_proxy.destroy()
            self.__dict__["_onstop_proxy"] = None
            
        if self._visualizer_proxy:
            #self._visualizer_proxy.destroy()
            self.__dict__["_visualizer_proxy"] = None

        if self.audio_ctx:
            try:
                self.audio_ctx.close()
            except Exception:
                pass
            self.__dict__["audio_ctx"] = None

    # ── Audio Visualizer ─────────────────────────────────────────────

    def start_visualizer(self):
        """Configures Web Audio AnalyserNode and canvas render loop."""
        try:
            self.audio_ctx = window.AudioContext.new()
            self.analyser = self.audio_ctx.createAnalyser()
            self.analyser.fftSize = 64  # Smooth representation
            
            source = self.audio_ctx.createMediaStreamSource(self.stream)
            source.connect(self.analyser)
            
            buffer_length = self.analyser.frequencyBinCount
            self.data_array = window.Uint8Array.new(buffer_length)
            
            canvas = self.__element__.querySelector(".ui-recorder-canvas")
            if canvas:
                canvas.width = canvas.clientWidth or 180
                canvas.height = canvas.clientHeight or 40
            
            def draw_loop(timestamp):
                if not self.recording:
                    return
                
                self.animation_id = window.requestAnimationFrame(self._visualizer_proxy)
                self.analyser.getByteFrequencyData(self.data_array)
                
                canvas = self.__element__.querySelector(".ui-recorder-canvas")
                if not canvas:
                    return
                
                ctx = canvas.getContext("2d")
                w = canvas.width
                h = canvas.height
                
                ctx.clearRect(0, 0, w, h)
                
                center_y = h / 2
                bar_width = (w / buffer_length) * 1.2
                x = 0
                
                for idx in range(buffer_length):
                    val = self.data_array.getItem(idx)
                    percent = val / 255.0
                    
                    # Double-sided waveform visualizer (like WhatsApp/Telegram)
                    wave_height = percent * h * 0.8
                    
                    # Sleek gradient color mapping
                    hue = 210 + (idx * 3)  # Bright blue to purple
                    ctx.fillStyle = f"hsla({hue}, 90%, 65%, {0.2 + percent * 0.8})"
                    
                    # Draw visual block
                    ctx.fillRect(x, center_y - wave_height / 2, bar_width - 1, wave_height)
                    x += bar_width
                    
            self._visualizer_proxy = ffi.create_proxy(draw_loop)
            self.animation_id = window.requestAnimationFrame(self._visualizer_proxy)
            
        except Exception as e:
            print(f"Failed to start visualizer: {e}")

    async def start_timer_loop(self):
        """Tick seconds timer in the background."""
        while self.recording:
            await asyncio.sleep(1)
            if not self.recording:
                break
            self.seconds_elapsed += 1
            self.formatted_time = self._format_seconds(self.seconds_elapsed)
            
    def _format_seconds(self, total_seconds):
        mins = total_seconds // 60
        secs = total_seconds % 60
        return f"{mins:02d}:{secs:02d}"

    # ── Styling & Markup ─────────────────────────────────────────────

    def style(self):
        """
        /* ── Host Widget ────────────────────────────────────── */
        ui-audio-recorder {
            display: inline-flex;
            justify-content: center;
        }

        .ui-recorder {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 1.5rem;
            width: 200px;
            height: 200px;
            border-radius: 1.5rem;
            background: var(--bg-secondary, rgba(30, 41, 59, 0.7));
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-color, rgba(255, 255, 255, 0.08));
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
            font-family: inherit;
        }

        .ui-recorder-active {
            border-color: rgba(239, 68, 68, 0.3);
            box-shadow: 0 10px 30px rgba(239, 68, 68, 0.15);
        }

        /* ── Circular Button ───────────────────────────────── */
        .ui-recorder-btn {
            position: relative;
            width: 72px;
            height: 72px;
            border-radius: 50%;
            border: none;
            background: linear-gradient(135deg, var(--accent-color, #3b82f6) 0%, #8b5cf6 100%);
            color: #ffffff;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4);
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 10;
        }

        .ui-recorder-btn:hover:not(:disabled) {
            transform: scale(1.06);
            box-shadow: 0 6px 20px rgba(139, 92, 246, 0.6);
        }

        .ui-recorder-btn:active:not(:disabled) {
            transform: scale(0.96);
        }

        .ui-recorder-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .ui-recorder-active .ui-recorder-btn {
            background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);
            box-shadow: 0 4px 20px rgba(239, 68, 68, 0.5);
        }

        /* ── Pulse Rings ────────────────────────────────────── */
        .ui-recorder-pulse-ring {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: rgba(239, 68, 68, 0.35);
            animation: ui-recorder-pulse 2s infinite ease-out;
            pointer-events: none;
            z-index: 1;
        }

        @keyframes ui-recorder-pulse {
            0% {
                transform: translate(-50%, -50%) scale(0.9);
                opacity: 0.8;
            }
            100% {
                transform: translate(-50%, -50%) scale(1.6);
                opacity: 0;
            }
        }

        /* ── Icons ─────────────────────────────────────────── */
        .ui-recorder-btn svg {
            width: 28px;
            height: 28px;
            transition: transform 0.2s;
        }

        .ui-recorder-btn .ui-recorder-icon-stop {
            display: none;
        }

        .ui-recorder-active .ui-recorder-btn .ui-recorder-icon-mic {
            display: none;
        }

        .ui-recorder-active .ui-recorder-btn .ui-recorder-icon-stop {
            display: block;
            animation: ui-recorder-stop-pop 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }

        @keyframes ui-recorder-stop-pop {
            0% { transform: scale(0.4); }
            100% { transform: scale(1); }
        }

        /* ── Audio Visualizer ────────────────────────────────── */
        .ui-recorder-visualizer-container {
            width: 100%;
            height: 36px;
            margin-top: 1rem;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .ui-recorder-canvas {
            width: 100%;
            height: 100%;
            border-radius: 0.5rem;
        }

        /* ── Metadata display ────────────────────────────────── */
        .ui-recorder-meta {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.25rem;
            margin-top: 1rem;
            text-align: center;
            width: 100%;
        }

        .ui-recorder-status {
            font-size: 0.775rem;
            font-weight: 500;
            color: var(--text-secondary, #94a3b8);
            letter-spacing: 0.01em;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .ui-recorder-timer {
            font-family: 'JetBrains Mono', 'Courier New', monospace;
            font-size: 1.15rem;
            font-weight: 600;
            color: #ef4444;
            letter-spacing: 0.04em;
            text-shadow: 0 0 8px rgba(239, 68, 68, 0.3);
            animation: ui-recorder-blink 1s steps(5, start) infinite;
        }

        @keyframes ui-recorder-blink {
            to { visibility: hidden; }
        }
        """

    def template(self):
        """
        <div class="ui-recorder {recording and 'ui-recorder-active' or ''}">
            <button 
                class="ui-recorder-btn" 
                onclick="{toggle_recording}" 
                {disabled_attr}>
                <svg class="ui-recorder-icon-mic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                    <line x1="12" y1="19" x2="12" y2="22"></line>
                </svg>
                <svg class="ui-recorder-icon-stop" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect>
                </svg>
                <div class="ui-recorder-pulse-ring" if="{recording}"></div>
            </button>
            
            <div class="ui-recorder-visualizer-container" if="{visualizer_enabled and recording}">
                <canvas class="ui-recorder-canvas"></canvas>
            </div>
            
            <div class="ui-recorder-meta" if="{show_meta}">
                <span class="ui-recorder-status">{status_text}</span>
                <span class="ui-recorder-timer" if="{recording}">{formatted_time}</span>
            </div>
        </div>
        """


# ── Server Actions (RPC Endpoint Methods) ───────────────────────────

@server_action
def save_audio_chunk(session_id: str, chunk_index: int, base64_data: str, content_type: str = "audio/webm") -> dict:
    """
    Saves a chunk of audio to the uploads/audio/<session_id>/ directory.
    Creates the directory if it doesn't exist.
    """
    try:
        # Determine extension from MIME content type
        ext = "webm"
        if "ogg" in content_type:
            ext = "ogg"
        elif "wav" in content_type:
            ext = "wav"
        elif "mp4" in content_type:
            ext = "mp4"
            
        session_dir = UPLOAD_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = session_dir / f"chunk_{chunk_index:04d}.{ext}"
        
        # Decode base64 bytes
        audio_bytes = base64.b64decode(base64_data)
        
        # Write binary chunk
        file_path.write_bytes(audio_bytes)
        
        print(f"[AudioRecorder Server] Saved chunk {chunk_index} for session {session_id} to {file_path}")
        
        return {
            "success": True,
            "file_path": str(file_path),
            "session_id": session_id,
            "chunk_index": chunk_index
        }
    except Exception as e:
        print(f"[AudioRecorder Server] Error saving chunk: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@server_action
def combine_audio_chunks(session_id: str) -> dict:
    """
    Combines all chunk files found in the session directory into a single output
    file, then deletes the temp folder.

    The output extension is derived from the actual chunk files on disk rather
    than a MIME type passed from the client. This avoids the mismatch between
    the blob MIME type (used when saving) and `MediaRecorder.mimeType` (which
    can differ and was the root cause of 0-byte output files).
    """
    try:
        session_dir = UPLOAD_DIR / session_id
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        if not session_dir.exists():
            return {
                "success": False,
                "error": f"Session directory not found: {session_dir}"
            }

        # Discover all chunk files and sort them numerically.
        # Pattern: chunk_NNNN.<ext>  (e.g. chunk_0000.ogg, chunk_0001.webm)
        chunk_files = sorted(
            session_dir.glob("chunk_*"),
            key=lambda p: int(p.stem.split("_")[1])
        )

        if not chunk_files:
            return {
                "success": False,
                "error": "No chunk files found in session directory"
            }

        # Use the extension of the first chunk as the canonical format.
        ext = chunk_files[0].suffix.lstrip(".")
        output_file = UPLOAD_DIR / f"{session_id}.{ext}"

        # Concatenate all chunks in order.
        with open(output_file, "wb") as out_f:
            for chunk_file in chunk_files:
                out_f.write(chunk_file.read_bytes())

        print(
            f"[AudioRecorder Server] Combined {len(chunk_files)} chunks "
            f"into {output_file} ({output_file.stat().st_size} bytes)"
        )

        # Clean up chunk directory.
        for f in session_dir.glob("*"):
            f.unlink()
        session_dir.rmdir()

        return {
            "success": True,
            "file_path": str(output_file),
            "session_id": session_id
        }

    except Exception as e:
        print(f"[AudioRecorder Server] Error combining chunks: {e}")
        return {
            "success": False,
            "error": str(e)
        }
