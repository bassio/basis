import json
from basis.shared.component import Component, IS_CLIENT, py_event
from basis.shared.reactive import computed

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = ffi = None


MAX_COLUMNS = 6


class Schedule(Component):
    """
    A premium daily appointment schedule component with a vertical time-axis,
    configurable tick intervals, dynamic column rendering, and all-day event support.

    Attributes:
        entries:       List of appointment dicts (the data source).
        time_attr:     Key name in each entry dict for the appointment time (HH:MM 24h).
        duration_attr: Key name in each entry dict for duration in minutes.
        all_day_attr:  Key name in each entry dict that marks it as an all-day event.
        columns:       List of column spec dicts: [{"key": "...", "label": "..."}, ...].
        tick_interval: Minutes between time-axis ticks (e.g. 15, 20, 30, 60).
        start_hour:    First hour of the day shown (0-23).
        end_hour:      Last hour shown (exclusive).
        title:         Optional header title for the schedule.
    """
    __tag__ = "ui-schedule"

    entries = []
    time_attr = "time"
    duration_attr = "duration"
    all_day_attr = "all_day"
    columns = []
    tick_interval = 30
    start_hour = 6
    end_hour = 20
    title = ""

    # ── Helpers ──────────────────────────────────────────────────────

    def _parse_entries(self):
        raw = self.entries
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raw = []
        return raw or []

    def _parse_columns(self):
        cols = self.columns
        if isinstance(cols, str):
            try:
                cols = json.loads(cols)
            except (json.JSONDecodeError, TypeError):
                cols = []
        return list(cols) if cols else []

    def _build_col_fields(self, entry, cols):
        """Pre-compute col_0 .. col_N values from entry dict for template use."""
        fields = {}
        for i in range(MAX_COLUMNS):
            if i < len(cols):
                fields[f"c{i}"] = str(entry.get(cols[i].get("key", ""), ""))
            else:
                fields[f"c{i}"] = ""
        return fields

    # ── Computed Properties ──────────────────────────────────────────

    @computed(dependencies=["start_hour", "end_hour"])
    def total_minutes(self):
        try:
            return (int(self.end_hour) - int(self.start_hour)) * 60
        except (ValueError, TypeError):
            return 14 * 60

    @computed(dependencies=["columns"])
    def resolved_columns(self):
        return self._parse_columns()

    @computed(dependencies=["columns"])
    def has_columns(self):
        cols = self._parse_columns()
        return len(cols) > 0

    @computed(dependencies=["columns"])
    def col_count(self):
        return min(len(self._parse_columns()), MAX_COLUMNS)

    # Column header labels – pre-extracted for direct template use
    @computed(dependencies=["columns"])
    def h0(self):
        c = self._parse_columns()
        return c[0]["label"] if len(c) > 0 else ""

    @computed(dependencies=["columns"])
    def h1(self):
        c = self._parse_columns()
        return c[1]["label"] if len(c) > 1 else ""

    @computed(dependencies=["columns"])
    def h2(self):
        c = self._parse_columns()
        return c[2]["label"] if len(c) > 2 else ""

    @computed(dependencies=["columns"])
    def h3(self):
        c = self._parse_columns()
        return c[3]["label"] if len(c) > 3 else ""

    @computed(dependencies=["columns"])
    def h4(self):
        c = self._parse_columns()
        return c[4]["label"] if len(c) > 4 else ""

    @computed(dependencies=["columns"])
    def h5(self):
        c = self._parse_columns()
        return c[5]["label"] if len(c) > 5 else ""

    @computed(dependencies=["start_hour", "end_hour", "tick_interval"])
    def time_slots(self):
        try:
            s = int(self.start_hour)
            e = int(self.end_hour)
            interval = int(self.tick_interval)
        except (ValueError, TypeError):
            s, e, interval = 6, 20, 30

        if interval <= 0:
            interval = 30
        total = (e - s) * 60
        slots = []
        minute = 0
        while minute <= total:
            abs_minutes = s * 60 + minute
            h = abs_minutes // 60
            m = abs_minutes % 60
            period = "AM" if h < 12 else "PM"
            display_h = h % 12
            if display_h == 0:
                display_h = 12
            label = f"{display_h}:{m:02d} {period}"
            top_pct = (minute / total * 100) if total > 0 else 0
            slots.append({
                "label": label,
                "minutes": abs_minutes,
                "top_pct": top_pct,
                "is_hour": m == 0,
            })
            minute += interval
        return slots

    @computed(dependencies=["entries", "time_attr", "duration_attr",
                            "all_day_attr", "start_hour", "end_hour",
                            "tick_interval", "columns"])
    def positioned_entries(self):
        raw = self._parse_entries()
        cols = self._parse_columns()
        if not raw:
            return []

        try:
            s = int(self.start_hour)
            e = int(self.end_hour)
            interval = int(self.tick_interval)
        except (ValueError, TypeError):
            s, e, interval = 6, 20, 30

        total = (e - s) * 60
        if total <= 0:
            return []

        t_attr = str(self.time_attr) if self.time_attr else "time"
        d_attr = str(self.duration_attr) if self.duration_attr else "duration"
        ad_attr = str(self.all_day_attr) if self.all_day_attr else "all_day"

        result = []
        for idx, entry in enumerate(raw):
            if not isinstance(entry, dict):
                continue
            if entry.get(ad_attr):
                continue
            time_str = entry.get(t_attr, "")
            if not time_str:
                continue
            try:
                parts = str(time_str).split(":")
                h = int(parts[0])
                m = int(parts[1]) if len(parts) > 1 else 0
            except (ValueError, IndexError):
                continue

            abs_min = h * 60 + m
            offset = abs_min - s * 60
            if offset < 0:
                offset = 0

            try:
                dur = int(entry.get(d_attr, interval))
            except (ValueError, TypeError):
                dur = interval

            top_pct = (offset / total) * 100
            height_pct = (dur / total) * 100
            if top_pct + height_pct > 100:
                height_pct = 100 - top_pct

            pe = {
                "idx": idx,
                "time_display": str(time_str),
                "top_pct": top_pct,
                "height_pct": height_pct,
                "column_index": 0,
                "column_count": 1,
            }
            # Pre-compute column values
            pe.update(self._build_col_fields(entry, cols))
            result.append(pe)

        result.sort(key=lambda x: x["top_pct"])
        return result

    @computed(dependencies=["entries", "all_day_attr", "columns"])
    def all_day_entries(self):
        raw = self._parse_entries()
        cols = self._parse_columns()
        if not raw:
            return []

        ad_attr = str(self.all_day_attr) if self.all_day_attr else "all_day"
        result = []
        for idx, entry in enumerate(raw):
            if not isinstance(entry, dict):
                continue
            if entry.get(ad_attr):
                # Build summary from columns for chip display
                parts = [str(entry.get(c.get("key", ""), "")) for c in cols if entry.get(c.get("key", ""), "")]
                summary = " · ".join(parts) if parts else f"Event {idx + 1}"
                ad = {"idx": idx, "summary": summary}
                ad.update(self._build_col_fields(entry, cols))
                result.append(ad)
        return result

    # ── Event Handlers ───────────────────────────────────────────────

    def on_entry_click(self, event):
        curr = event.target
        entry_data = None
        while curr:
            if hasattr(curr, "getAttribute") and curr.getAttribute("data-entry-idx"):
                idx_str = curr.getAttribute("data-entry-idx")
                try:
                    idx = int(idx_str)
                    raw = self._parse_entries()
                    if 0 <= idx < len(raw):
                        entry_data = raw[idx]
                except (ValueError, IndexError, TypeError):
                    pass
                break
            if hasattr(curr, "parentNode"):
                curr = curr.parentNode
            else:
                break

        if entry_data and IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "select",
                ffi.to_js({"detail": {"entry": entry_data}, "bubbles": True})
            ))

    # ── Style ────────────────────────────────────────────────────────

    def style(self):
        """
        ui-schedule {
            display: block;
            width: 100%;
            font-family: inherit;
            box-sizing: border-box;
        }

        /* ── Container ──────────────────────────────────────── */
        .schedule-container {
            background: var(--bg-secondary, #f8f9fa);
            border: 1px solid var(--border-color, #dcdcdc);
            border-radius: 12px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
            overflow: hidden;
        }

        /* ── Header ─────────────────────────────────────────── */
        .schedule-header {
            padding: 16px 20px 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--border-color, #dcdcdc);
        }
        .schedule-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-primary, #2e2e2e);
            letter-spacing: -0.01em;
            margin: 0;
        }

        /* ── All-Day Banner ─────────────────────────────────── */
        .schedule-all-day {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px 10px 74px;
            border-bottom: 1px solid var(--border-color, #dcdcdc);
            background: color-mix(in srgb, var(--accent-color, #007acc) 4%, var(--bg-secondary, #f8f9fa));
            min-height: 40px;
            flex-wrap: wrap;
        }
        .schedule-all-day-label {
            font-size: 0.68rem;
            font-weight: 600;
            color: var(--text-secondary, #7a7a7a);
            text-transform: uppercase;
            letter-spacing: 0.06em;
            flex-shrink: 0;
            width: 54px;
            margin-left: -54px;
            text-align: right;
            padding-right: 12px;
        }
        .schedule-all-day-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 14px;
            background: color-mix(in srgb, var(--accent-color, #007acc) 10%, transparent);
            border: 1px solid color-mix(in srgb, var(--accent-color, #007acc) 22%, transparent);
            border-left: 3px solid var(--accent-color, #007acc);
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 500;
            color: var(--text-primary, #2e2e2e);
            cursor: pointer;
            transition: all 0.2s ease;
            white-space: nowrap;
        }
        .schedule-all-day-chip:hover {
            background: color-mix(in srgb, var(--accent-color, #007acc) 18%, transparent);
            border-color: color-mix(in srgb, var(--accent-color, #007acc) 40%, transparent);
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        }

        /* ── Column Headers ─────────────────────────────────── */
        .schedule-col-headers {
            display: flex;
            align-items: center;
            padding: 8px 20px 8px 74px;
            border-bottom: 1px solid var(--border-color, #dcdcdc);
            background: var(--bg-secondary, #f8f9fa);
            gap: 0;
        }
        .schedule-col-header-time {
            min-width: 56px;
            flex-shrink: 0;
            font-size: 0.68rem;
            font-weight: 600;
            color: var(--text-secondary, #7a7a7a);
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }
        .schedule-col-header {
            flex: 1;
            font-size: 0.68rem;
            font-weight: 600;
            color: var(--text-secondary, #7a7a7a);
            text-transform: uppercase;
            letter-spacing: 0.06em;
            padding: 0 6px;
        }

        /* ── Grid Body ──────────────────────────────────────── */
        .schedule-body {
            position: relative;
            min-height: 600px;
        }

        /* ── Tick Lines ─────────────────────────────────────── */
        .schedule-tick {
            position: absolute;
            left: 0;
            right: 0;
            display: flex;
            align-items: flex-start;
            pointer-events: none;
            z-index: 1;
        }
        .schedule-tick-label {
            width: 54px;
            flex-shrink: 0;
            padding: 0 12px 0 8px;
            text-align: right;
            font-size: 0.7rem;
            font-weight: 500;
            color: var(--text-secondary, #7a7a7a);
            transform: translateY(-7px);
            user-select: none;
            line-height: 1;
            opacity: 0.7;
        }
        .schedule-tick-label-hour {
            font-weight: 600;
            color: var(--text-primary, #2e2e2e);
            font-size: 0.73rem;
            opacity: 1;
        }
        .schedule-tick-line {
            flex: 1;
            height: 1px;
            background: var(--border-color, #e5e7eb);
            opacity: 0.5;
        }
        .schedule-tick-line-hour {
            opacity: 1;
            background: var(--border-color, #d0d0d0);
        }

        /* ── Entry Cards ────────────────────────────────────── */
        .schedule-entry {
            position: absolute;
            left: 66px;
            right: 14px;
            z-index: 2;
            cursor: pointer;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .schedule-entry:hover {
            transform: scale(1.003) translateX(1px);
            z-index: 10;
        }
        .schedule-entry-card {
            display: flex;
            align-items: stretch;
            height: 100%;
            min-height: 28px;
            background: var(--bg-primary, #ffffff);
            border: 1px solid color-mix(in srgb, var(--border-color, #dcdcdc) 80%, transparent);
            border-left: 3px solid var(--accent-color, #007acc);
            border-radius: 6px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
            transition: box-shadow 0.15s ease, border-color 0.15s ease;
        }
        .schedule-entry:hover .schedule-entry-card {
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
            border-color: color-mix(in srgb, var(--accent-color, #007acc) 35%, var(--border-color, #dcdcdc));
        }
        .schedule-entry-time {
            display: flex;
            align-items: center;
            padding: 4px 10px;
            font-size: 0.72rem;
            font-weight: 600;
            color: var(--accent-color, #007acc);
            background: color-mix(in srgb, var(--accent-color, #007acc) 5%, transparent);
            white-space: nowrap;
            flex-shrink: 0;
            min-width: 52px;
            justify-content: center;
            border-right: 1px solid color-mix(in srgb, var(--accent-color, #007acc) 10%, transparent);
        }
        .schedule-entry-cols {
            display: flex;
            align-items: center;
            flex: 1;
            gap: 0;
            padding: 0;
            overflow: hidden;
        }
        .schedule-entry-col {
            flex: 1;
            font-size: 0.8rem;
            color: var(--text-primary, #2e2e2e);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            line-height: 1.4;
            padding: 4px 8px;
        }
        .schedule-entry-col-primary {
            font-weight: 600;
        }

        /* ── Empty State ────────────────────────────────────── */
        .schedule-empty {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 60px 20px;
            color: var(--text-secondary, #7a7a7a);
            text-align: center;
            gap: 8px;
        }
        .schedule-empty-icon {
            font-size: 2.5rem;
            opacity: 0.4;
        }
        .schedule-empty-text {
            font-size: 0.9rem;
            font-weight: 500;
        }

        /* ── Current Time Indicator ─────────────────────────── */
        .schedule-now-line {
            position: absolute;
            left: 54px;
            right: 0;
            height: 2px;
            background: #ef4444;
            z-index: 15;
            pointer-events: none;
        }
        .schedule-now-line::before {
            content: '';
            position: absolute;
            left: -4px;
            top: -3px;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ef4444;
        }
        """

    # ── Template ─────────────────────────────────────────────────────
    # Column values are pre-computed as c0..c5 to avoid nested for loops.

    def template(self):
        """
        <div class="schedule-container">
            <div class="schedule-header" if="{title}">
                <h3 class="schedule-title">{title}</h3>
            </div>

            <div class="schedule-all-day" if="{all_day_entries}">
                <span class="schedule-all-day-label">All day</span>
                <div for="ad" in="{all_day_entries}" key="idx"
                     class="schedule-all-day-chip"
                     data-entry-idx="{ad['idx']}"
                     onclick="{on_entry_click}">
                    {ad['summary']}
                </div>
            </div>

            <div class="schedule-col-headers" if="{has_columns}">
                <span class="schedule-col-header-time">Time</span>
                <span class="schedule-col-header" if="{h0}">{h0}</span>
                <span class="schedule-col-header" if="{h1}">{h1}</span>
                <span class="schedule-col-header" if="{h2}">{h2}</span>
                <span class="schedule-col-header" if="{h3}">{h3}</span>
                <span class="schedule-col-header" if="{h4}">{h4}</span>
                <span class="schedule-col-header" if="{h5}">{h5}</span>
            </div>

            <div class="schedule-body">
                <div for="slot" in="{time_slots}" key="label"
                     class="schedule-tick"
                     style="top: {slot['top_pct']}%">
                    <span class="schedule-tick-label {slot['is_hour'] and 'schedule-tick-label-hour' or ''}">{slot['label']}</span>
                    <div class="schedule-tick-line {slot['is_hour'] and 'schedule-tick-line-hour' or ''}"></div>
                </div>

                <div for="pe" in="{positioned_entries}" key="idx"
                     class="schedule-entry"
                     style="top: {pe['top_pct']}%; height: {pe['height_pct']}%"
                     data-entry-idx="{pe['idx']}"
                     onclick="{on_entry_click}">
                    <div class="schedule-entry-card">
                        <div class="schedule-entry-time">{pe['time_display']}</div>
                        <div class="schedule-entry-cols">
                            <span class="schedule-entry-col schedule-entry-col-primary" if="{pe['c0']}">{pe['c0']}</span>
                            <span class="schedule-entry-col" if="{pe['c1']}">{pe['c1']}</span>
                            <span class="schedule-entry-col" if="{pe['c2']}">{pe['c2']}</span>
                            <span class="schedule-entry-col" if="{pe['c3']}">{pe['c3']}</span>
                            <span class="schedule-entry-col" if="{pe['c4']}">{pe['c4']}</span>
                            <span class="schedule-entry-col" if="{pe['c5']}">{pe['c5']}</span>
                        </div>
                    </div>
                </div>

                <div class="schedule-empty" if="{not positioned_entries and not all_day_entries}">
                    <span class="schedule-empty-icon">📋</span>
                    <span class="schedule-empty-text">No appointments scheduled</span>
                </div>
            </div>
        </div>
        """
