import sys
import os
import re
from collections import defaultdict

from PyQt5.QtWidgets import (
    QWidget, QToolTip, QPushButton, QApplication, QMessageBox,
    QLabel, QLineEdit, QFileDialog, QVBoxLayout, QHBoxLayout,
    QTextEdit, QGroupBox, QSplitter, QFrame
)
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtCore import QCoreApplication, Qt

# Regex patterns (compiled once)
CHANNEL_ID_RE = re.compile(r'ChannelId\s*=\s*([a-zA-Z0-9\-]+)')
TIMESTAMP_RE = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
# Match ERROR or EXCEPTION block: everything until next timestamp block or end of file
ERROR_RE = re.compile(r'(?:ERROR|EXCEPTION)\s*\n(.*?)(?=\n\[?\d{4}-\d{2}-\d{2}|\Z)', re.DOTALL)
BLOCK_SPLIT_RE = re.compile(r'(?=\[\d{4}-\d{2}-\d{2})')

# Pattern for ServerConfiguration: channelId: <id>(<name>), serverId:
CONFIG_LINE_RE = re.compile(
    r'channelId:\s+([a-f0-9\-]+)\s*\(([^)]+)\)\s*,\s*serverId:',
    re.IGNORECASE
)


def load_camera_map(folder: str) -> tuple[dict, dict]:
    """
    Parse ServerConfiguration.log and return:
      id_to_name: {camera_id: name}
      name_to_ids: {name: [camera_id, ...]}
    """
    config_file = os.path.join(folder, 'ServerConfiguration.log')
    if not os.path.exists(config_file):
        return {}, {}

    id_to_name: dict[str, str] = {}
    name_to_ids: dict[str, list] = defaultdict(list)

    try:
        with open(config_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
            text = f.read()
        for m in CONFIG_LINE_RE.finditer(text):
            cam_id = m.group(1).strip()
            cam_name = m.group(2).strip()
            if cam_id not in id_to_name:
                id_to_name[cam_id] = cam_name
                name_to_ids[cam_name].append(cam_id)
    except Exception as e:
        print(f"[WARN] Cannot parse config: {e}")

    return id_to_name, name_to_ids


def parse_error_log(folder: str, id_to_name: dict) -> tuple[dict, list]:
    """
    Parse DevConError.log and return:
      camera_errors: {camera_id: {error_text: count}}
      all_raw_errors: [(timestamp, camera_id, error_text)]
    """
    error_file = os.path.join(folder, 'DevConError.log')
    if not os.path.exists(error_file):
        return {}, []

    camera_errors: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_raw_errors: list[tuple[str, str, str]] = []
    id_set = set(id_to_name.keys())

    try:
        with open(error_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
            content = f.read()

        # Split into blocks starting with [YYYY-MM-DD
        blocks = BLOCK_SPLIT_RE.split(content)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Extract channel ID — try embedded ChannelId first, then Thread=ChannelId
            ch_match = CHANNEL_ID_RE.search(block)
            if not ch_match:
                # Fallback: some lines start with "Thread=ChannelId = <id>"
                ch_match = re.search(r'Thread=ChannelId\s*=\s*([a-zA-Z0-9\-]+)', block)
            if not ch_match:
                continue

            channel_id = ch_match.group(1)
            # Only process cameras known from config
            if channel_id not in id_set:
                continue

            # Extract timestamp
            ts_match = TIMESTAMP_RE.search(block)
            timestamp = ts_match.group(1) if ts_match else "???"

            # Extract error text
            error_text = _extract_error_text(block)
            if not error_text:
                continue

            camera_errors[channel_id][error_text] += 1
            all_raw_errors.append((timestamp, channel_id, error_text))

    except Exception as e:
        print(f"[WARN] Cannot parse error log: {e}")

    return dict(camera_errors), all_raw_errors


def _extract_error_text(block: str) -> str | None:
    """Extract the main error description from a log block."""
    # Try EXCEPTION first, then ERROR
    for marker in ('EXCEPTION', 'ERROR'):
        idx = block.find(marker)
        if idx == -1:
            continue
        start = idx + len(marker)
        rest = block[start:].strip()
        if not rest:
            continue

        # Take first meaningful line
        lines = rest.split('\n')
        main_line = lines[0].strip()

        # Skip GUID-like lines and stack traces
        if re.match(r'^\{[0-9A-F\-]+\}$', main_line):
            # This is a GUID — take the next line if available
            if len(lines) > 1:
                main_line = lines[1].strip()
            else:
                continue

        # Another GUID check after potential skip
        if re.match(r'^\{[0-9A-F\-]+\}$', main_line):
            continue

        # Remove stack trace lines (lines starting with "at ")
        # Just use the first line which is the error message
        # Clean up
        main_line = re.sub(r'\s+', ' ', main_line).strip()
        if len(main_line) > 200:
            main_line = main_line[:197] + '...'

        if main_line and len(main_line) > 3:
            return main_line

    return None


def generate_report(folder: str, id_to_name: dict, camera_errors: dict) -> str:
    """Generate a text report grouped by camera."""
    lines = []
    lines.append("=" * 60)
    lines.append("  ОТЧЁТ ОБ ОШИБКАХ КАМЕР")
    lines.append(f"  Камер с ошибками: {len(camera_errors)}")
    lines.append("=" * 60)
    lines.append("")

    for channel_id in sorted(camera_errors.keys()):
        errors_dict = camera_errors[channel_id]
        name = id_to_name.get(channel_id, '???')
        total = sum(errors_dict.values())
        lines.append(f"[{channel_id}]")
        lines.append(f"  Имя: {name}")
        lines.append(f"  Всего ошибок: {total}")
        lines.append("  Ошибки:")
        sorted_errors = sorted(errors_dict.items(), key=lambda x: x[1], reverse=True)
        for i, (error, count) in enumerate(sorted_errors, 1):
            lines.append(f"    {i}. [{count}x] {error}")
        lines.append("")

    report_path = os.path.join(folder, '_camera_errors_report.txt')
    report_text = '\n'.join(lines)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    return report_path


def resolve_camera_ids(query: str, id_to_name: dict, name_to_ids: dict) -> list[str]:
    """
    Resolve a search query to a list of camera IDs.
    Supports exact ID match, partial ID match, and name substring match (case-insensitive).
    """
    query = query.strip()

    # Exact ID match
    if query in id_to_name:
        return [query]

    # Partial ID match (contains)
    id_matches = [cid for cid in id_to_name if query.lower() in cid.lower()]
    if id_matches:
        return id_matches

    # Name substring match (case-insensitive)
    name_matches = []
    q_lower = query.lower()
    for name, ids in name_to_ids.items():
        if q_lower in name.lower():
            name_matches.extend(ids)

    return list(set(name_matches))


def build_camera_detail(ids: list[str], all_raw_errors: list, id_to_name: dict) -> str:
    """Build detailed error text for specific camera IDs."""
    lines = []
    id_set = set(ids)

    filtered = [(ts, cid, err) for ts, cid, err in all_raw_errors if cid in id_set]

    if not filtered:
        return "Ошибки для указанных камер не найдены."

    for cam_id in sorted(ids):
        name = id_to_name.get(cam_id, '???')
        cam_errors = [(ts, err) for ts, cid, err in filtered if cid == cam_id]
        if not cam_errors:
            continue

        lines.append(f"{'='*60}")
        lines.append(f"  Камера: {name}")
        lines.append(f"  ID: {cam_id}")
        lines.append(f"  Количество ошибок: {len(cam_errors)}")
        lines.append(f"{'='*60}")

        for ts, err in cam_errors:
            lines.append(f"  [{ts}] {err}")
        lines.append("")

    return '\n'.join(lines) if lines else "Ошибки для указанных камер не найдены."


# ==================== GUI ====================

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.current_folder = os.getcwd()
        self.id_to_name: dict = {}
        self.name_to_ids: dict = {}
        self.camera_errors: dict = {}
        self.all_raw_errors: list = []
        self._init_ui()

    def _init_ui(self):
        QToolTip.setFont(QFont('Segoe UI', 10))

        self.setWindowTitle("So_easy_read_errors — Анализ логов камер")
        self.setGeometry(400, 200, 900, 650)
        self.setMinimumSize(800, 500)

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # --- Top bar ---
        top_bar = QHBoxLayout()

        self.btn_open_dir = QPushButton("📁 Открыть папку с логами")
        self.btn_open_dir.setToolTip("Выбрать папку, содержащую DevConError.log и ServerConfiguration.log")
        self.btn_open_dir.clicked.connect(self.choose_dir)
        self.btn_open_dir.setMinimumHeight(32)
        top_bar.addWidget(self.btn_open_dir)

        self.lbl_dir = QLabel(f"Текущая папка: {self.current_folder}")
        self.lbl_dir.setWordWrap(True)
        top_bar.addWidget(self.lbl_dir, 1)

        main_layout.addLayout(top_bar)

        # --- Separator ---
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)

        # --- Search bar ---
        search_group = QGroupBox("Поиск ошибок камеры")
        search_layout = QHBoxLayout()
        search_group.setLayout(search_layout)

        search_layout.addWidget(QLabel("ID или имя камеры:"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите ID камеры, ID или часть названия...")
        self.search_input.returnPressed.connect(self.do_search)
        self.search_input.setToolTip(
            "Поддерживается:\n"
            "  • Полный ID: 37475bad-4ae9-408f-80aa-ae589f004112\n"
            "  • Часть ID: 37475bad\n"
            "  • Имя камеры: Продажа\n"
            "  • Часть имени: сварочный"
        )
        search_layout.addWidget(self.search_input, 1)

        self.btn_search = QPushButton("🔍 Найти")
        self.btn_search.clicked.connect(self.do_search)
        self.btn_search.setMinimumHeight(28)
        search_layout.addWidget(self.btn_search)

        main_layout.addWidget(search_group)

        # --- Action buttons ---
        actions_layout = QHBoxLayout()

        self.btn_report = QPushButton("📋 Сгенерировать отчёт (все камеры)")
        self.btn_report.setToolTip("Анализировать DevConError.log и сгруппировать ошибки по камерам")
        self.btn_report.clicked.connect(self.generate_all_report)
        self.btn_report.setMinimumHeight(32)
        actions_layout.addWidget(self.btn_report)

        self.btn_open_report = QPushButton("📄 Открыть отчёт")
        self.btn_open_report.setToolTip("Открыть последний сгенерированный _camera_errors_report.txt")
        self.btn_open_report.clicked.connect(self.open_last_report)
        self.btn_open_report.setMinimumHeight(32)
        actions_layout.addWidget(self.btn_open_report)

        self.btn_quit = QPushButton("✖ Выход")
        self.btn_quit.clicked.connect(QCoreApplication.instance().quit)
        self.btn_quit.setMinimumHeight(32)
        actions_layout.addWidget(self.btn_quit)

        main_layout.addLayout(actions_layout)

        # --- Results area ---
        self.results = QTextEdit()
        self.results.setReadOnly(True)
        self.results.setFont(QFont('Consolas', 9))
        self.results.setPlaceholderText(
            "Результаты поиска и отчёты будут отображены здесь.\n\n"
            "1. Нажмите 'Открыть папку с логами' для выбора папки\n"
            "2. Нажмите 'Сгенерировать отчёт' для анализа всех камер\n"
            "3. Или введите ID/имя камеры и нажмите 'Найти'"
        )
        main_layout.addWidget(self.results)

        # --- Status bar ---
        self.status_label = QLabel("Готово. Укажите папку с логами.")
        self.status_label.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        main_layout.addWidget(self.status_label)

        self.refresh_buttons()

    def refresh_buttons(self):
        has_folder = os.path.isdir(self.current_folder)
        has_config = os.path.isfile(os.path.join(self.current_folder, 'ServerConfiguration.log'))
        has_errors = os.path.isfile(os.path.join(self.current_folder, 'DevConError.log'))

        self.btn_report.setEnabled(has_folder and has_config and has_errors)
        self.btn_search.setEnabled(has_folder and has_errors)

        if has_folder and not has_config:
            self.status_label.setText("⚠ ServerConfiguration.log не найден в выбранной папке")
        elif has_folder and not has_errors:
            self.status_label.setText("⚠ DevConError.log не найден в выбранной папке")
        elif has_folder and has_config and has_errors:
            self.status_label.setText(f"✓ Папка загружена: {self.current_folder}")
        else:
            self.status_label.setText("Укажите папку с логами")

    def load_data(self):
        """Load config and parse error log for the current folder."""
        self.id_to_name, self.name_to_ids = load_camera_map(self.current_folder)

        if not self.id_to_name:
            QMessageBox.warning(self, "Внимание",
                                "Не удалось загрузить ServerConfiguration.log.\n"
                                "Файл не найден или не содержит записей о камерах.")
            return False

        self.results.append(f"<b>Загружена конфигурация: {len(self.id_to_name)} камер.</b>")
        self.results.append("<i>Теперь можете сгенерировать отчёт или искать по камере.</i>")
        self.results.append("")
        return True

    def ensure_data_loaded(self) -> bool:
        """Ensure config is loaded; if not, try to load. Returns True on success."""
        if not self.id_to_name:
            return self.load_data()
        return True

    def choose_dir(self):
        dirname = QFileDialog.getExistingDirectory(self, "Выбрать папку с логами", self.current_folder)
        if dirname:
            self.current_folder = dirname
            os.chdir(dirname)
            self.lbl_dir.setText(f"Текущая папка: {self.current_folder}")
            self.id_to_name = {}
            self.name_to_ids = {}
            self.camera_errors = {}
            self.all_raw_errors = []
            self.results.clear()
            self.refresh_buttons()
            self.load_data()

    def generate_all_report(self):
        if not self.ensure_data_loaded():
            return

        self.results.append("<b>Анализирую DevConError.log...</b>")

        self.camera_errors, self.all_raw_errors = parse_error_log(
            self.current_folder, self.id_to_name
        )

        if not self.camera_errors:
            self.results.append("Ошибки камер не найдены или файл DevConError.log пуст.")
            self.status_label.setText("Ошибки не найдены")
            return

        report_path = generate_report(self.current_folder, self.id_to_name, self.camera_errors)

        # Show summary in the text area
        lines = []
        lines.append(f"<b>Найдено камер с ошибками: {len(self.camera_errors)}</b>")
        lines.append(f'<i>Полный отчёт сохранён: {report_path}</i>')
        lines.append("")

        for channel_id in sorted(self.camera_errors.keys()):
            errors_dict = self.camera_errors[channel_id]
            name = self.id_to_name.get(channel_id, '???')
            total = sum(errors_dict.values())
            sorted_errors = sorted(errors_dict.items(), key=lambda x: x[1], reverse=True)

            lines.append(f"<b>▸ {name}</b> &nbsp; <span style='color:gray'>[{channel_id}] ({total} ошибок)</span>")
            for error, count in sorted_errors[:5]:  # Top 5 per camera in preview
                lines.append(f" &nbsp; &nbsp; [{count}x] {error}")
            if len(sorted_errors) > 5:
                lines.append(f" &nbsp; &nbsp; <i>... ещё {len(sorted_errors)-5} типов ошибок</i>")
            lines.append("")

        self.results.append('\n'.join(lines).replace('\n', '<br>'))
        self.status_label.setText(
            f"Отчёт готов: {len(self.camera_errors)} камер с ошибками"
        )

    def do_search(self):
        if not self.ensure_data_loaded():
            return

        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Ошибка", "Введите ID или имя камеры для поиска")
            return

        # Make sure we have parsed errors
        if not self.all_raw_errors:
            self.camera_errors, self.all_raw_errors = parse_error_log(
                self.current_folder, self.id_to_name
            )
            if not self.all_raw_errors:
                self.results.append("Ошибки камер не найдены в DevConError.log.")
                return

        ids = resolve_camera_ids(query, self.id_to_name, self.name_to_ids)

        if not ids:
            suggestions = []
            q_lower = query.lower()
            for name in self.name_to_ids:
                # Simple Levenshtein-ish: find names with common substrings
                if any(part in name.lower() for part in q_lower.split()):
                    suggestions.append(f"  • {name} ({'/'.join(self.name_to_ids[name])[:20]}...)")

            msg = f"Камеры по запросу '<b>{query}</b>' не найдены."
            if suggestions:
                msg += "\n\nВозможно вы имели в виду:\n" + '\n'.join(suggestions[:10])

            QMessageBox.information(self, "Результат", msg)
            self.status_label.setText(f"По запросу '{query}' ничего не найдено")
            return

        detail = build_camera_detail(ids, self.all_raw_errors, self.id_to_name)

        # Clear and show results
        self.results.clear()

        names = [f"{self.id_to_name.get(cid, '?')} [{cid}]" for cid in ids]
        self.results.append(f"<b>Результаты поиска по:</b> {query}")
        self.results.append(f"<i>Найдено камер: {len(ids)} — {', '.join(names[:5])}</i>")
        if len(ids) > 5:
            self.results.append(f"<i>... ещё {len(ids)-5} камер</i>")
        self.results.append("")

        # Convert plain text detail to HTML
        for line in detail.split('\n'):
            if line.startswith('='):
                self.results.append(f"<hr>")
            elif line.startswith('  Камера:') or line.startswith('  Количество'):
                self.results.append(f"<b>{line}</b>")
            elif line.startswith('  ['):
                self.results.append(f"<span style='color:#555'>{line}</span>")
            elif line.startswith('  Ошибки:') or line.startswith('    '):
                self.results.append(f"<span style='color:#333'>{line}</span>")
            elif line.startswith('  ID:'):
                self.results.append(f"<span style='color:gray;font-size:small'>{line}</span>")
            else:
                self.results.append(line)

        # Scroll to top
        self.results.moveCursor(QTextCursor.Start)

        self.status_label.setText(
            f"Найдено камер: {len(ids)} — запрос: '{query}'"
        )

    def open_last_report(self):
        report_path = os.path.join(self.current_folder, '_camera_errors_report.txt')
        if os.path.exists(report_path):
            os.startfile(report_path)
        else:
            QMessageBox.information(self, "Файл не найден",
                                    "Сначала сгенерируйте отчёт кнопкой 'Сгенерировать отчёт'.")

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, "Выход",
            "Закрыть приложение?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            event.accept()
        else:
            event.ignore()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Optional: set application font
    font = QFont('Segoe UI', 10)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
