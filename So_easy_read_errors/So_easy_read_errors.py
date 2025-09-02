from email.policy import default
import sys, os, re
from PyQt5.QtWidgets import (QWidget, QToolTip, QPushButton, QApplication, QMessageBox, QLabel, QLineEdit, QFileDialog, QVBoxLayout)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QCoreApplication
import shutil



#----------------------------- Логика(основные функции) ------------------------------------

def generate_name_id_list():
    camera_id_name = {} # Список соответствий id к имени камеры
    config_file = 'ServerConfiguration.log'
    target_text_name = 'channelId: '

    # Проверяем существование файла
    if not os.path.exists(config_file):
        QMessageBox.warning(None, "Ошибка", f"Файл {config_file} не найден в текущей директории")
        return camera_id_name

    try:
        # Создаем копию файла с расширением .txt вместо переименования
        filename = os.path.splitext(config_file)[0]
        temp_file = filename + '_temp.txt'
        shutil.copy2(config_file, temp_file)
        
        with open(temp_file, 'r', encoding='utf-8', errors='ignore') as file:
            for line in file:
                index = line.find(target_text_name)
                if index != -1:
                    substring = line[index + len(target_text_name):].strip()
                    bracket_index = substring.find('(')
                    if bracket_index != -1:
                        camera_id = substring[:bracket_index].strip()
                        name_substring = substring[bracket_index:].strip()
                        coma_index = name_substring.find(',')
                        if coma_index != -1:
                            camera_name = name_substring[:coma_index].strip()
                            if camera_id not in camera_id_name:
                                camera_id_name[camera_id] = camera_name

        # Удаляем временный файл
        os.remove(temp_file)
        
    except Exception as e:
        print(f"Ошибка при обработке файла конфигурации: {e}")
        # Если временный файл существует, пытаемся его удалить
        if 'temp_file' in locals() and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
    
    return camera_id_name
    # На этом этапе, на выходе имеем словарь camera_id_name, с заполненными id - имена камер


def convert_error_cams():  # Надо написать все в 1 функции
    camera_id_name = generate_name_id_list() # Список соответствий id к имени камеры
    camera_errors = {} # Список с множеством значений в который положим id камер как ключ и множество значений ошибок к этой камере
    camera_error_file = 'DevConError.log'

    # Проверяем существование файла с ошибками
    if not os.path.exists(camera_error_file):
        QMessageBox.warning(None, "Ошибка", f"Файл {camera_error_file} не найден в текущей директории")
        return

    try:
       # Создаем копию файла с ошибками
        filename2 = os.path.splitext(camera_error_file)[0]
        temp_file = filename2 + '_temp.txt'
        shutil.copy2(camera_error_file, temp_file)

        # Регулярное выражение для извлечения ChannelId в переменную channel_id_re и текста ошибок в переменную error_re
        channel_id_re = re.compile(r'ChannelId\s*=\s*([a-zA-Z0-9\-]+)')  
        error_re = re.compile(r'(EXCEPTION|ERROR)(.*?)(?=$$|\Z)', re.DOTALL)

        # Открываем файл для чтения целиком и кладем в переменную content
        with open(temp_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        blocks = re.split(r'\[\d{4}-\d{2}-\d{2}', content)    # Разбиваем на блоки по времени от первой '[' до следующей такой же.

        # Идем циклом по блокам в получившемся списке блоков
        for block in blocks:
            if not block.strip():
                continue            # Если блок пустой, пропускаем его идем в следующую итерацию цикла

            full_block = '[' + block  # Восстанавливаем временную метку

            # Поиск ChannelId в блоке текста
            channel_match = channel_id_re.search(full_block)
            if not channel_match:
                continue
            channel_id = channel_match.group(1) #Записывает в переменную, то что нашло регулярное выражение в первой группе выделенной скобками, которые в регулярнке у на сравны ([a-zA-Z0-9\-]+), то есть id камеры.

            # Поиск ошибки в блоке текста
            error_match = error_re.search(full_block)
            if not error_match:
                continue

            # Извлечение и очистка текста ошибки 
            error_text = error_match.group(2).strip()
            lines = error_text.split('\n')   # Разбиваем на строки
            main_line = lines[0].strip() # Берём первую строку — она содержит основное сообщение об ошибке
            main_line = re.sub(r' at [^ ]+\.([^ ]+\.)*', '', main_line) # Удаляем стек вызовов (всё, что начинается с "at System.")
            main_line = re.sub(r'\(\d+\)', '', main_line)  # Удаляем коды ошибок в скобках, если они не важны
            main_line = re.sub(r'\s+', ' ', main_line).strip() # Убираем лишние пробелы
            error_summary = main_line[:200] # Ограничиваем длину



            # Добавляем в словарь id-шники камер и их значения ошибок в виде множества значений после ключа
            if channel_id not in camera_errors:
                camera_errors[channel_id] = {}
        
            if error_summary not in camera_errors[channel_id]:
                camera_errors[channel_id][error_summary] = 1
            else:
                camera_errors[channel_id][error_summary] += 1

        # Сохраняем результат в файл
        output_file = '_camera_errors_report.txt'
        with open(output_file, 'w', encoding='utf-8') as out_file:
            for channel_id, errors_dict in sorted(camera_errors.items()):
                out_file.write(f"ID: {channel_id}\nNAME: {camera_id_name.get(channel_id, 'Не найдено')}\n")
                # Сортируем ошибки по количеству повторений (по убыванию)
                sorted_errors = sorted(errors_dict.items(), key=lambda x: x[1], reverse=True)
                for i, (error, count) in enumerate(sorted_errors, 1):
                    out_file.write(f"{i}. {error} ({count})\n")
                out_file.write("\n")

        #os.rename(analys_file2, filename2 + file_type2)
        
        # Удаляем временный файл
        os.remove(temp_file)
        
    except Exception as e:
        print(f"Ошибка при обработке файла ошибок: {e}")
        # Если временный файл существует, пытаемся его удалить
        if 'temp_file' in locals() and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        raise


def open_file(file_name):
    os.startfile(file_name)


def error_cams_log():
    try:
        convert_error_cams()
        open_file('_camera_errors_report.txt')
    except:
        pass



# Функция поиска ошибок по конкретной камере
def search_camera_errors(camera_id):
    # Переименовываем файл для чтения
    error_file = 'DevConError.log'
    temp_file = 'DevConError.txt'
    os.rename(error_file, temp_file)

    results = []

    # Регулярное выражение для поиска даты и ошибки
    timestamp_re = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
    channel_id_re = re.compile(r'ChannelId\s*=\s*([a-zA-Z0-9\-]+)')
    error_re = re.compile(r'(EXCEPTION|ERROR)(.*?)(?=$$|\Z)', re.DOTALL)

    with open(temp_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Разбиваем на блоки по времени
    blocks = re.split(r'\[', content)          # Работает, но не записывает время, поправил что бы не удаляло дату.


    for block in blocks:
        if not block.strip():
            continue

        full_block = '[' + block  # Восстанавливаем временную метку

        # Поиск ID камеры
        channel_match = channel_id_re.search(full_block)
        if not channel_match or channel_match.group(1) != camera_id:
            continue

        # Поиск даты
        ts_match = timestamp_re.search(full_block)
        timestamp = ts_match.group(1) if ts_match else "Неизвестно"

        # Поиск текста ошибки
        error_match = error_re.search(full_block)
        if not error_match:
            continue

        error_text = error_match.group(2).strip()
        error_summary = error_text.split('\n')[0].strip()
        error_summary = re.sub(r'\s+', ' ', error_summary)[:200]

        results.append((timestamp, error_summary))

    os.rename(temp_file, error_file)

    if not results:
        QMessageBox.information(None, "Результат", "Ошибки для камеры не найдены")
        return

    # Сохраняем в файл
    output_file = f'_camera_errors_{camera_id}.txt'
    with open(output_file, 'w', encoding='utf-8') as out_file:
        for timestamp, error in results:
            out_file.write(f"[{timestamp}]\n{error}\n\n")

    os.startfile(output_file)


#----------------------------- Интерфейс ------------------------------------
class Example(QWidget):

    def __init__(self):
        super().__init__()

        self.initUI()


    def initUI(self):

        QToolTip.setFont(QFont('SansSerif', 10))

        self.setToolTip('Это <b>So_easy_read_errors</b> виджет')

        btn = QPushButton('Найти проблемные камеры и сопоставить имена', self)
        btn.setToolTip('<b>Вывод камер с ошибками в логах</b>')
        btn.resize(btn.sizeHint())
        btn.move(10, 80)
        btn.clicked.connect(error_cams_log)

        btn2 = QPushButton('Поиск', self)
        btn2.resize(btn2.sizeHint())
        btn2.move(335, 129)
        btn2.clicked.connect(self.get_input_search)

        btn_dir = QPushButton('Выбрать папку с логами..', self)
        btn_dir.resize(btn_dir.sizeHint())
        btn_dir.move(10, 10)
        btn_dir.clicked.connect(self.chose_dir)

        qbtn = QPushButton('Выход', self)
        qbtn.clicked.connect(QCoreApplication.instance().quit)
        qbtn.resize(qbtn.sizeHint())
        qbtn.move(480, 129)

        search_cam_lbl = QLabel('Введите id камеры', self)
        search_cam_lbl.move(110, 110)

        self.dir_lbl = QLabel(f"Текущий рабочий каталог:\n {os.getcwd()}", self)
        self.dir_lbl.move(10, 35)

        self.search_cam_input = QLineEdit(self)
        self.search_cam_input.move(10,130)
        self.search_cam_input.resize(315, 20)
        

        self.setGeometry(600, 400, 565, 160)
        self.setFixedSize(565, 160)
        self.setWindowTitle('So_easy_read_errors')
        self.show()


    def closeEvent(self, event):

        reply = QMessageBox.question(self, 'Сообщение',
            "Вы уверены что хотите закрыть окно?", QMessageBox.Yes |
            QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            event.accept()
        else:
            event.ignore()


    def get_input_search(self):
        input_data = self.search_cam_input.text().strip()
        if not input_data:
            QMessageBox.warning(self, 'Ошибка', 'ID камеры не задан')
            return
        # Пытаемся найти ошибки по ID камеры
        search_camera_errors(input_data) #Проверил, данные в функцию из поля точно уходят


    def chose_dir(self):
        dirname = QFileDialog.getExistingDirectory(self, "Выбрать директорию", ".")
        if dirname:
            os.chdir(dirname)
            self.dir_lbl.setText(f"Текущий рабочий каталог:\n {dirname}")


#----------------------------- Запуск приложения ------------------------------------
if __name__ == '__main__':

    app = QApplication(sys.argv)
    ex = Example()
    sys.exit(app.exec_())