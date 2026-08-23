from basis.shared.component import Component
from basis.shared.reactive import computed
import datetime
import calendar

try:
    from pyscript import window, document, ffi
    IS_CLIENT = True
except ImportError:
    window = document = ffi = None
    IS_CLIENT = False


class Calendar(Component):
    """
    A slick, premium monthly calendar component with responsive design.
    
    Attributes:
        selected_date: The selected date (YYYY-MM-DD).
        current_year: Currently viewed year (default: current year).
        current_month: Currently viewed month (1-12, default: current month).
        update: Store path or target identifier for two-way reactivity.
    """
    __tag__ = "ui-calendar"

    selected_date = datetime.date.today().strftime("%Y-%m-%d")
    current_year = datetime.date.today().year
    current_month = datetime.date.today().month
    update = ""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name == "selected_date" and value:
            try:
                parts = value.split("-")
                if len(parts) == 3:
                    y, m, d = map(int, parts)
                    
                    with self.refrain() as refrained:
                        refrained.current_year = y
                        refrained.current_month = m
                        
            except Exception as e:
                print("Error in Calendar.__setattr__ sync:", e)


    @computed(dependencies=["current_year", "current_month", "selected_date"])
    def days(self):
        try:
            year = int(self.current_year)
            month = int(self.current_month)
        except (ValueError, TypeError):
            today = datetime.date.today()
            year = today.year
            month = today.month

        today = datetime.date.today()
        today_str = today.strftime("%Y-%m-%d")
        sel_str = str(self.selected_date) if self.selected_date else ""

        cal = calendar.Calendar(firstweekday=6) # Sunday start
        days_list = []
        for y, m, d, wd in cal.itermonthdays4(year, month):
            date_str = f"{y:04d}-{m:02d}-{d:02d}"
            
            is_current = (m == month)
            is_today = (date_str == today_str)
            is_selected = (date_str == sel_str)

            classes = ["day-cell"]
            if not is_current:
                classes.append("other-month")
            else:
                classes.append("current-month")
            if is_today:
                classes.append("is-today")
            if is_selected:
                classes.append("is-selected")

            days_list.append({
                "year": y,
                "month": m,
                "day_num": d,
                "date_str": date_str,
                "is_current": is_current,
                "is_today": is_today,
                "is_selected": is_selected,
                "classes": " ".join(classes)
            })
        return days_list

    @computed(dependencies=["current_month"])
    def month_name(self):
        try:
            m = int(self.current_month)
        except (ValueError, TypeError):
            m = datetime.date.today().month
        return calendar.month_name[m]

    @computed(dependencies=[])
    def years_range(self):
        try:
            cy = datetime.date.today().year
        except Exception:
            cy = 2026
        return list(range(cy - 50, cy + 50))


    def on_prev(self, event):
        try:
            m = int(self.current_month)
            y = int(self.current_year)
        except (ValueError, TypeError):
            today = datetime.date.today()
            m = today.month
            y = today.year
            
        if m == 1:
            self.current_month = 12
            self.current_year = y - 1
        else:
            self.current_month = m - 1

    def on_next(self, event):
        try:
            m = int(self.current_month)
            y = int(self.current_year)
        except (ValueError, TypeError):
            today = datetime.date.today()
            m = today.month
            y = today.year

        if m == 12:
            self.current_month = 1
            self.current_year = y + 1
        else:
            self.current_month = m + 1

    def on_month_select_change(self, event):
        try:
            self.current_month = int(event.target.value)
        except Exception as e:
            print("Error changing month:", e)

    def on_year_select_change(self, event):
        try:
            self.current_year = int(event.target.value)
        except Exception as e:
            print("Error changing year:", e)

    def on_today(self, event):
        today = datetime.date.today()
        today_str = today.strftime("%Y-%m-%d")
        self.selected_date = today_str
        self.current_year = today.year
        self.current_month = today.month
        if self.update:
            setattr(self, self.update, today_str)
        self.dispatch_change_event()

    def on_select(self, event):
        curr = event.target
        date_str = None
        while curr:
            if hasattr(curr, "getAttribute") and curr.getAttribute("data-date"):
                date_str = curr.getAttribute("data-date")
                break
            if hasattr(curr, "parentNode"):
                curr = curr.parentNode
            else:
                break
        
        if date_str:
            self.selected_date = date_str
            if self.update:
                setattr(self, self.update, date_str)
            self.dispatch_change_event()

    def dispatch_change_event(self):
        if IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "change",
                ffi.to_js({"detail": {"selected_date": self.selected_date}, "bubbles": True})
            ))

    def style(self):
        """
        ui-calendar {
            display: block;
            width: 100%;
            max-width: 380px;
            background: var(--bg-secondary, #f8f9fa);
            border: 1px solid var(--border-color, #dcdcdc);
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            padding: 16px;
            font-family: inherit;
            user-select: none;
            box-sizing: border-box;
        }

        .calendar-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
            gap: 8px;
        }

        .calendar-controls {
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .calendar-selects {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .calendar-select {
            background: var(--bg-primary, #fff);
            border: 1px solid var(--border-color, #dcdcdc);
            border-radius: 6px;
            padding: 4px 24px 4px 8px;
            font-size: 0.85rem;
            font-weight: 500;
            color: var(--text-primary, #2e2e2e);
            cursor: pointer;
            outline: none;
            appearance: none;
            background-image: url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%237a7a7a' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 8px center;
            background-size: 12px;
        }

        .calendar-btn {
            background: var(--bg-primary, #fff);
            border: 1px solid var(--border-color, #dcdcdc);
            color: var(--text-primary, #2e2e2e);
            border-radius: 6px;
            width: 28px;
            height: 28px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s ease;
            font-size: 0.9rem;
            font-weight: 600;
        }

        .calendar-btn:hover {
            background: var(--hover-bg, #f1f3f5);
            border-color: var(--text-secondary, #7a7a7a);
        }

        .calendar-weekdays {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            text-align: center;
            margin-bottom: 8px;
        }

        .weekday-cell {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-secondary, #7a7a7a);
            padding: 6px 0;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .calendar-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 4px;
        }

        .day-cell {
            aspect-ratio: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.85rem;
            font-weight: 500;
            border-radius: 50%;
            cursor: pointer;
            transition: all 0.15s ease;
            color: var(--text-primary, #2e2e2e);
            position: relative;
        }

        .day-cell.other-month {
            color: var(--text-secondary, #7a7a7a);
            opacity: 0.4;
        }

        .day-cell:hover {
            background: var(--hover-bg, #e9ecef);
        }

        .day-cell.is-today {
            font-weight: 700;
            color: var(--accent-color, #007acc);
            background: color-mix(in srgb, var(--accent-color, #007acc) 10%, transparent);
        }

        .day-cell.is-selected {
            background: var(--accent-color, #007acc) !important;
            color: #ffffff !important;
            font-weight: 600;
        }
        """

    def template(self):
        """
        <div>
            <div class="calendar-header">
                <div class="calendar-selects">
                    <select class="calendar-select" bind="{current_month}">
                        <option value="1" {selected}="{int(current_month) == 1}">January</option>
                        <option value="2" {selected}="{int(current_month) == 2}">February</option>
                        <option value="3" {selected}="{int(current_month) == 3}">March</option>
                        <option value="4" {selected}="{int(current_month) == 4}">April</option>
                        <option value="5" {selected}="{int(current_month) == 5}">May</option>
                        <option value="6" {selected}="{int(current_month) == 6}">June</option>
                        <option value="7" {selected}="{int(current_month) == 7}">July</option>
                        <option value="8" {selected}="{int(current_month) == 8}">August</option>
                        <option value="9" {selected}="{int(current_month) == 9}">September</option>
                        <option value="10" {selected}="{int(current_month) == 10}">October</option>
                        <option value="11" {selected}="{int(current_month) == 11}">November</option>
                        <option value="12" {selected}="{int(current_month) == 12}">December</option>
                    </select>
                    <select class="calendar-select" bind="{current_year}">
                        <option for="y" in="{years_range}" key="y" {selected}="{y == int(current_year)}">{y}</option>
                    </select>


                </div>
                <div class="calendar-controls">
                    <button class="calendar-btn" onclick="{on_prev}">⟵</button>
                    <button class="calendar-btn" onclick="{on_today}" title="Go to Today">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px;">
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                            <line x1="16" y1="2" x2="16" y2="6"></line>
                            <line x1="8" y1="2" x2="8" y2="6"></line>
                            <line x1="3" y1="10" x2="21" y2="10"></line>
                            <text x="12" y="19" font-size="10" font-family="sans-serif" font-weight="900" text-anchor="middle" fill="currentColor" stroke="none">T</text>
                        </svg>
                    </button>
                    <button class="calendar-btn" onclick="{on_next}">⟶</button>
                </div>
            </div>
            
            <div class="calendar-weekdays">
                <div class="weekday-cell">Su</div>
                <div class="weekday-cell">Mo</div>
                <div class="weekday-cell">Tu</div>
                <div class="weekday-cell">We</div>
                <div class="weekday-cell">Th</div>
                <div class="weekday-cell">Fr</div>
                <div class="weekday-cell">Sa</div>
            </div>

            <div class="calendar-grid">
                <div for="d" in="{days}" key="date_str" class="{d['classes']}" data-date="{d['date_str']}" onclick="{on_select}">
                    {d['day_num']}
                </div>
            </div>
        </div>
        """
