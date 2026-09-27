"""Editable Russian pitch deck; generation and verification run in Actions only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Presentation generation is allowed only in GitHub Actions')

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

OUT = Path('artifacts/energotechhub-2026')
OUT.mkdir(parents=True, exist_ok=True)
STEM = 'Sheaft_Energotechhub_2026_RU'
ROOT = 'https://github.com/a-a-k/sheaft-tsfg-experiments'
REPORT = ROOT + '/blob/main/docs/results/revision-v2/final/FINAL_REPORT_RU.md'
PROGRAM = 'https://etechhubspb.ru/accelerator'
BFG = 'https://bfg.ai/bfg-aps/'
FONT = 'DejaVu Sans'
FONT_DIR = Path('/usr/share/fonts/truetype/dejavu')
C = dict(navy='102831', dark='0A1A21', paper='F4F4ED', white='FFFFFF',
         mint='A6E2C6', teal='176B63', orange='E98D52', ink='15343C',
         muted='526C72', dim='AEC5C8', line='C9D7D2', soft='E6ECE5',
         card='193943', pale='DAEEE2')
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(16), Inches(9)
prs.core_properties.title = 'Sheaft — Энерготехнохаб Петербург · Осень 2026'
prs.core_properties.subject = 'Быстрое производственное планирование и проверка исполнения'
prs.core_properties.author = 'Sheaft'
prs.core_properties.keywords = 'Sheaft, APS, ТЭК, Энерготехнохаб, 2026'
manifest = []


def rgb(value):
    return RGBColor.from_string(C.get(value, value))


def rect(s, x, y, w, h, color, radius=False, stroke=None):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                            Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = rgb(color)
    if stroke:
        sh.line.color.rgb = rgb(stroke)
        sh.line.width = Pt(1)
    else:
        sh.line.fill.background()
    if radius:
        sh.adjustments[0] = .1
    return sh


def line(s, x1, y1, x2, y2, color='line', width=1.4):
    sh = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    sh.line.color.rgb = rgb(color)
    sh.line.width = Pt(width)
    return sh


def wrap(text, size, width, bold):
    font = ImageFont.truetype(str(FONT_DIR / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')), size * 4)
    lines = []
    for paragraph in text.split('\n'):
        words, current = paragraph.split(), ''
        for word in words:
            candidate = (current + ' ' + word).strip()
            if current and font.getlength(candidate) / 4 > width * 72:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def text(s, value, x, y, w, h, size=22, color='ink', bold=False, align=None, link=None):
    assert x >= 0 and y >= 0 and x+w <= 16.01 and y+h <= 9.01, (value, x, y, w, h)
    actual = size
    while actual > 12:
        lines = wrap(value, actual, w-.03, bold)
        if len(lines) * actual * 1.19 <= h*72:
            break
        actual -= 1
    assert len(wrap(value, actual, w-.03, bold))*actual*1.19 <= h*72+2, (value, actual, h)
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for i, row in enumerate(wrap(value, actual, w-.03, bold)):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = row
        p.font.name, p.font.size, p.font.bold = FONT, Pt(actual), bold
        p.font.color.rgb = rgb(color)
        p.space_before, p.space_after, p.line_spacing = Pt(0), Pt(0), 1.04
        if align is not None:
            p.alignment = align
        if link:
            for r in p.runs:
                r.hyperlink.address = link
    manifest[-1]['texts'].append(value)
    return box


def pill(s, value, x, y, w, dark=False, tone='teal'):
    rect(s, x, y, w, .38, 'card' if dark else 'pale', True)
    text(s, value, x+.14, y+.055, w-.28, .26, 12, 'mint' if dark else tone, True)


def base(section, title=None, dark=False, note='', sources=()):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb('navy' if dark else 'paper')
    manifest.append(dict(number=len(prs.slides), section=section, title=title or 'Sheaft',
                         texts=[], sources=list(sources), notes=note))
    text(s, 'SHEAFT', .65, .35, 2.3, .34, 17, 'mint' if dark else 'teal', True)
    text(s, section.upper(), 4, .38, 11.3, .3, 12, 'dim' if dark else 'muted', align=PP_ALIGN.RIGHT)
    if title:
        text(s, title, .65, 1.0, 14.65, 1.2, 36, 'white' if dark else 'ink', True)
    line(s, .65, 8.35, 15.35, 8.35, 'card' if dark else 'line', .8)
    text(s, 'Энерготехнохаб Петербург · Осень 2026', .65, 8.55, 11.5, .24, 10, 'dim' if dark else 'muted')
    text(s, f'{len(prs.slides):02}', 14.5, 8.48, .8, .36, 16, 'mint' if dark else 'teal', True, PP_ALIGN.RIGHT)
    if note or sources:
        s.notes_slide.notes_text_frame.text = note + '\n\nИсточники:\n' + '\n'.join(sources)
    return s


def foot(s, value, dark=False, link=None):
    text(s, value, .65, 7.8, 14.7, .42, 11, 'dim' if dark else 'muted', link=link)


def card(s, x, y, w, h, title, body, num=None, dark=False):
    rect(s, x, y, w, h, 'card' if dark else 'white', True)
    offset = .35
    if num:
        text(s, num, x+.3, y+.25, w-.6, .5, 24, 'mint' if dark else 'teal', True)
        offset = .95
    text(s, title, x+.3, y+offset, w-.6, .87, 23, 'white' if dark else 'ink', True)
    text(s, body, x+.3, y+offset+1.05, w-.6, h-offset-1.25, 18, 'dim' if dark else 'muted')


def build():
    s = base('Научно-технологический акселератор', dark=True,
             note='Представить Sheaft как инженерный прототип для быстрого построения и проверки производственных планов. Фокус заявки — совместный пилот с заказчиком из ТЭК. Число 74,73 с относится к APS-BASIC на синтетических входах, а не ко всем ограничениям сразу. Примерное время: 25 секунд.', sources=[REPORT, PROGRAM])
    pill(s, 'ИНЖЕНЕРНЫЙ ПРОТОТИП', .65, 1.32, 3.5, True)
    text(s, 'Производственный план,\nкоторый можно быстро\nпересчитать и проверить', .65, 2.13, 10.8, 2.9, 43, 'white', True)
    text(s, 'Sheaft · сценарное планирование\nдля производственных и ремонтных участков ТЭК', .7, 5.62, 10.15, 1.15, 24, 'dim')
    for i, (x, w) in enumerate(((11.8, 2.2), (12.4, 2.8), (11.2, 2.5), (12, 3.0))):
        rect(s, x, 2.2+i*.77, w, .42, 'mint' if i != 2 else 'orange', True)
        line(s, 10.95, 2.7+i*.77, 15.2, 2.7+i*.77, 'card', 1)
    foot(s, 'Предложение пилота · результаты и границы применимости открыты', True, REPORT)

    s = base('01 / Производственная задача', 'Одно изменение запускает цепочку перепланирования',
             note='Это предлагаемый сценарий применения, а не кейс существующего клиента. Станок становится недоступен, за ним возникает очередь, задерживаются следующие операции. Общая бригада или стенд усиливают зависимость. Нужно быстро оценить последствия для заказов и выбрать допустимый вариант. Примерное время: 30 секунд.')
    text(s, 'Станок недоступен. Срочный заказ добавлен. Общая бригада занята.', .7, 2.36, 14.5, .6, 24)
    for x, title, label, tone in [(1.0, 'Операция 1', 'обработка', 'teal'), (6.0, 'Операция 2', 'ожидание', 'orange'), (11, 'Операция 3', 'сдвиг срока', 'teal')]:
        rect(s, x, 3.67, 4, 1.55, 'white', True)
        rect(s, x, 3.67, .09, 1.55, tone)
        text(s, title, x+.27, 3.98, 3.5, .45, 23, bold=True)
        text(s, label, x+.27, 4.57, 3.5, .32, 16, tone)
    for x in (5.2, 10.2):
        text(s, '→', x, 4.1, .65, .6, 28, 'teal')
    rect(s, .7, 6.05, 14.6, 1.17, 'navy', True)
    text(s, 'Решение диспетчера: какой план выполнить теперь и какие сроки изменятся?', 1.03, 6.33, 13.9, .65, 25, 'white', True)
    foot(s, 'Иллюстрация целевой задачи. Экономический эффект на предприятии ещё предстоит измерить.')

    s = base('02 / Первый заказчик', 'Точка входа — ремонтно-производственный участок ТЭК',
             note='Предлагаем начать с дискретных маршрутов: изготовление деталей или восстановление узлов энергетического оборудования. Здесь можно явно задать станки, операции, буферы и общие ресурсы. Это перенос проверенной модели на данные предприятия; непрерывное управление технологическими установками в первый пилот не включено. Примерное время: 30 секунд.', sources=[PROGRAM])
    card(s, .7, 2.67, 4.6, 4.3, 'Кто использует', 'Диспетчер и плановый отдел\n\nВладелец результата — руководитель участка', '01')
    card(s, 5.7, 2.67, 4.6, 4.3, 'Что планируем', 'Изготовление деталей и ремонт узлов\n\nОперации, оборудование, бригады и места ожидания', '02')
    card(s, 10.7, 2.67, 4.6, 4.3, 'Какое решение', 'Перестроить последовательность работ после изменения\n\nПроверить сроки и ограничения', '03')
    foot(s, 'Предлагаемый сегмент пилота; действующие заказчики и отраслевой эффект не заявляются.')

    s = base('03 / Продукт', 'От исходных заказов — к проверенному варианту плана', dark=True,
             note='Показываем целевой пользовательский процесс. Уже реализованы алгоритмы построения и проверки, форматы данных, сценарии и результаты. Пользовательский интерфейс и интеграция с ERP/MES — этап продуктовой разработки. При найденной блокировке текущий симулятор сообщает о ней; эффективное автоматическое исправление входит в доработку. Примерное время: 35 секунд.', sources=[REPORT])
    steps = [('Данные', 'Заказы, маршруты,\nдоступное оборудование'), ('Построение', 'Назначения, очереди\nи времена операций'), ('Проверка', 'Сроки, ожидания,\nресурсы и блокировки'), ('Решение', 'Сравнение сценариев\nи выбор диспетчера')]
    for i, (title, body) in enumerate(steps):
        x = .7+i*3.75
        card(s, x, 2.83, 3.4, 3.6, title, body, str(i+1).zfill(2), True)
        if i < 3:
            text(s, '→', x+3.42, 4.07, .35, .5, 21, 'mint')
    text(s, 'Сценарии: отказ оборудования · новый заказ · изменение доступного ресурса', .75, 6.93, 14.5, .55, 21, 'mint')
    foot(s, 'Алгоритмический прототип работает; интерфейс и интеграции входят в план пилота.', True)

    s = base('04 / Инженерный задел', 'Один продукт. Отдельные алгоритмы для разных задач.',
             note='LIST выбирает назначения и очереди; DAG быстро рассчитывает времена готового плана в простой модели; DES проверяет исполнение с совместными ограничениями. Независимость переходов позволяет сопоставлять результаты. Научно-инженерный задел — формализованная модель, воспроизводимая проверка и масштабируемый вычислительный модуль. Математическая новизна самих LIST, DAG и DES не заявляется. TSFG-агрегация остаётся отдельным исследовательским направлением. Примерное время: 40 секунд.', sources=[REPORT])
    card(s, .7, 2.8, 4.55, 3.9, 'LIST', 'Строит новый план\n\nВыбирает оборудование и порядок операций', 'ПЛАНИРОВАНИЕ')
    card(s, 5.72, 2.8, 4.55, 3.9, 'DAG', 'Проверяет готовый план\n\nФиксированные очереди, неограниченные буферы', 'БЫСТРЫЙ РАСЧЁТ')
    card(s, 10.74, 2.8, 4.55, 3.9, 'DES', 'Моделирует исполнение\n\nКонечные буферы и общие ресурсы', 'СОВМЕСТНЫЕ ОГРАНИЧЕНИЯ')
    text(s, 'Независимая проверка переходов + открытые протоколы и результаты', .75, 7.03, 14.3, .48, 23, 'teal', True)
    foot(s, 'Потоковая агрегация TSFG — отдельное направление для совместимых непрерывных процессов.')

    s = base('05 / Измеренный результат', 'Миллион операций — за 74,73 секунды', dark=True,
             note='Это максимум медиан по десяти уникальным миллионным входам, каждый с тремя повторами. На двух размерах выполнено 60 основных запусков; все планы прошли проверку допустимости. Время включает запуск, чтение, построение и полный вывод, но не последующую валидацию. Ограничения измеренной модели: альтернативные станки, предшествования, поступления; буферы неограничены, общие ресурсы не учитываются в построении. Оптимальность не заявлена. Примерное время: 40 секунд.', sources=[REPORT, ROOT+'/blob/main/docs/results/revision-v2/final/APS_MATRIX_REPORT_RU.md'])
    text(s, '74,73', .7, 2.58, 9.5, 1.95, 110, 'mint', True)
    text(s, 'секунды на построение и полный вывод плана', .9, 4.88, 8.55, 1.18, 26, 'white')
    for y, n, label in [(2.65, '60', 'корректных основных запусков'), (4.05, '10 × 3', 'миллионных входов × повторы'), (5.55, '1 CPU', 'ограничение вычислительного процесса')]:
        text(s, n, 11.0, y, 4.15, .7, 37, 'white', True)
        text(s, label, 11.03, y+.75, 4.05, .62, 17, 'dim')
    foot(s, 'Синтетические F1/F2 · APS-BASIC · максимум медиан · без конечных буферов и общих ресурсов.', True, REPORT)

    s = base('06 / Совместные ограничения', 'Буферы и общие ресурсы уже учитываются вместе',
             note='Разделяем построение и исполнение. Совместная модель исполнения прошла 135 комбинаций Mk01 и 405 проверок состояния к сроку с независимыми движками и рациональным эталоном. В регрессионных случаях есть последовательный резервный план. Следующий шаг — эффективное построение и исправление расписания при этих ограничениях. Функция остаётся частью продукта; миллионный замер её быстродействие не подтверждает. Примерное время: 40 секунд.', sources=[REPORT, ROOT+'/blob/main/docs/PBR_EXACT_V2_2_RU.md'])
    pill(s, 'ПРОВЕРКА ИСПОЛНЕНИЯ РЕАЛИЗОВАНА', .7, 2.52, 5.25)
    text(s, '135', .77, 3.2, 5.5, 1.2, 70, 'teal', True)
    text(s, 'совместных сценариев Mk01', .8, 4.57, 5.85, .6, 23)
    text(s, '405', .8, 5.46, 2.15, .82, 43, 'ink', True)
    text(s, 'проверок состояния\nк заданным срокам', 3.03, 5.5, 3.55, .93, 20, 'muted')
    rect(s, 7.2, 2.6, 8.1, 4.62, 'navy', True)
    text(s, 'Следующий шаг', 7.62, 2.98, 7.22, .6, 25, 'mint', True)
    text(s, 'Автоматически строить и исправлять эффективное расписание с теми же ограничениями', 7.62, 3.96, 7.17, 1.55, 29, 'white', True)
    text(s, 'Базовый последовательный вариант есть в регрессионных случаях.', 7.62, 6.05, 7.1, .83, 19, 'dim')
    foot(s, 'Подтверждена корректность исполнения на проверенной серии; масштаб и качество построения требуют замеров.', link=REPORT)

    s = base('07 / Рыночная гипотеза', 'Быстрый пересчёт как преимущество перед классом APS',
             note='Сохраняем согласованную гипотезу преимущества перед классом APS с BFG как первым ориентиром. Поставщик публикует миллион операций за 45 минут. Наши 74,73 секунды получены в другой модели и среде. Сравнение качества, ограничений и аппаратуры ещё нужно выровнять. Число 36× не используем как доказанное конкурентное преимущество. Примерное время: 30 секунд.', sources=[BFG, REPORT])
    for x, title, value, detail in [(.7, 'BFG APS · ориентир', '45 минут', 'Показатель на сайте поставщика\nдля миллиона операций'), (8.2, 'Sheaft · эксперимент', '74,73 с', 'APS-BASIC: миллион операций\nна проверенных синтетических входах')]:
        rect(s, x, 2.7, 7.05, 3.25, 'white', True)
        text(s, title, x+.33, 3.02, 6.35, .62, 23, bold=True)
        text(s, value, x+.33, 3.93, 6.35, .9, 45, 'teal', True)
        text(s, detail, x+.33, 5.04, 6.35, .73, 18, 'muted')
    text(s, 'Проверим преимущество на одинаковых данных, ограничениях и критериях качества.', .78, 6.38, 14.45, .96, 26, bold=True)
    foot(s, 'Разные условия измерения. Это рыночный ориентир, а не доказанное ускорение относительно BFG.', link=BFG)

    s = base('08 / Совместный пилот', 'Один участок. Одни данные. Заранее заданные критерии.',
             note='Запрос к акселератору — найти владельца участка и данных. Сначала восстанавливаем исторический план, фиксируем ограничения и базовый способ планирования. Затем сравниваем на одних входах и проверяем выбранные изменения. Численные пороги времени и экономического эффекта согласуем до оценочной серии. Не выдаём цели пилота за уже достигнутый эффект. Примерное время: 40 секунд.')
    rows = [('Допустимость', 'Все ограничения модели соблюдены; нет скрытых блокировок.'), ('Качество плана', 'Выпуск к сроку и опоздание не хуже согласованной базы.'), ('Скорость решения', 'Полное время пересчёта и проверки укладывается в окно диспетчера.'), ('Польза на участке', 'Сравниваем ручные исправления, простои и незавершённые работы.')]
    for i, (title, desc) in enumerate(rows):
        y = 2.63+i*1.12
        text(s, str(i+1).zfill(2), .75, y+.05, .8, .48, 23, 'teal', True)
        text(s, title, 1.85, y, 3.85, .72, 23, bold=True)
        text(s, desc, 6.15, y+.02, 8.72, .83, 21, 'muted')
        if i < 3:
            line(s, 1.85, y+.94, 15, y+.94)
    foot(s, 'Предлагаемые критерии. Пороговые значения и контрольная выборка фиксируются до пилотных измерений.')

    s = base('09 / Маршрут внедрения', 'От проверенного прототипа — к работе на данных заказчика', dark=True,
             note='Маршрут соответствует фокусу программы на трансфер технологии. Сначала данные и проверяемая модель, затем доработка планировщика под реальные ограничения, потом теневой режим с диспетчером, после приёмки — интеграция. Сроки определяются после обследования данных и объёма работ. Примерное время: 35 секунд.', sources=[PROGRAM])
    line(s, 1.3, 3.03, 14.55, 3.03, 'mint', 2)
    stages = [('Модель участка', 'Маршруты, оборудование,\nбуферы и общие ресурсы'), ('Доработка', 'Построение и исправление\nплана с ограничениями'), ('Теневой режим', 'Рекомендации диспетчеру\nи сравнение с текущей практикой'), ('Интеграция', 'Обмен данными с ERP/MES\nпосле приёмки пилота')]
    for i, (title, desc) in enumerate(stages):
        x = .75+i*3.77
        dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x+.12), Inches(2.81), Inches(.44), Inches(.44))
        dot.fill.solid(); dot.fill.fore_color.rgb=rgb('orange' if i==1 else 'mint'); dot.line.fill.background()
        text(s, str(i+1).zfill(2), x, 3.7, 3.3, .62, 28, 'mint', True)
        text(s, title, x, 4.53, 3.32, .97, 25, 'white', True)
        text(s, desc, x, 5.72, 3.25, 1.28, 18, 'dim')
    foot(s, 'План работ для согласования с индустриальным заказчиком; календарь определяется после обследования.', True)

    s = base('10 / Коммерциализация', 'Маршрут трансфера — пилот, доработка, лицензирование',
             note='Коммерческая модель является предложением. Оплачиваемый пилот или НИОКР подтверждает применимость; лицензирование вычислительного модуля и сопровождение позволяет тиражировать; интеграционный партнёр помогает встроить решение в системы заказчика. Цена, выручка, патенты и заключённые договоры не заявляются. Примерное время: 30 секунд.')
    card(s, .7, 2.65, 4.58, 4.25, 'Пилот / НИОКР', 'Совместная постановка задачи и проверка результата\n\nЗаказчик получает модель участка и критерии приёмки', '01')
    card(s, 5.71, 2.65, 4.58, 4.25, 'Лицензия модуля', 'Расчёт планов и проверка сценариев в контуре заказчика\n\nСопровождение и развитие', '02')
    card(s, 10.72, 2.65, 4.58, 4.25, 'Интеграция', 'Подключение к ERP/MES вместе с промышленным ИТ-партнёром\n\nТиражирование на другие участки', '03')
    foot(s, 'Предлагаемая модель коммерциализации. Состав поставки и права на компоненты закрепляются перед договором.')

    s = base('11 / Запрос к акселератору', dark=True,
             note='Финальный запрос: промышленный заказчик с подходящим участком, доступ к историческим данным и участие технолога/диспетчера. Предлагаем вместе определить маршрут НИОКР или пилота. Открытый экспериментальный пакет уже доступен. Данные команды и контакт выступающего уточняются отдельно и не выдумываются. Примерное время: 25 секунд.', sources=[ROOT, PROGRAM])
    text(s, 'Нужен индустриальный\nпартнёр для совместного\nпилота Sheaft', .7, 1.68, 11.4, 2.5, 46, 'white', True)
    for i, label in enumerate(('Ремонтно-производственный участок', 'Исторические данные и эксперт предприятия', 'Согласованный маршрут пилота или НИОКР')):
        text(s, '0'+str(i+1), .8, 4.77+i*.78, .8, .47, 21, 'mint', True)
        text(s, label, 1.85, 4.77+i*.78, 12.6, .56, 24, 'white')
    foot(s, 'Открытые результаты: github.com/a-a-k/sheaft-tsfg-experiments', True, ROOT)

    s = base('Приложение A / Готовность', 'Что уже работает и что предстоит проверить',
             note='Эту таблицу использовать в ответах экспертов. Состояния относятся к текущему прототипу, а не к готовой промышленной поставке. Формальный TRL без согласованной оценки не назначаем.', sources=[REPORT])
    statuses = [('Построение APS-BASIC', 'Реализовано и измерено', '60 корректных основных запусков'), ('Исполнение с буферами и ресурсами', 'Реализовано и проверено', '135 сценариев Mk01; независимые движки'), ('Допустимый последовательный план', 'Регрессионный механизм', 'Ограниченные случаи; без гарантии качества'), ('Эффективное совместное планирование', 'Доработка в пилоте', 'Скорость и качество пока не измерены'), ('Интерфейс и ERP/MES', 'Продуктовая разработка', 'Нет заявленного промышленного внедрения')]
    for i, (a,b,c) in enumerate(statuses):
        y=2.53+i*.98
        if i%2==0:rect(s,.7,y-.08,14.6,.89,'white',True)
        text(s,a,.94,y+.07,5.1,.66,18,bold=True)
        text(s,b,6.38,y+.07,3.7,.66,17,'teal',True)
        text(s,c,10.47,y+.07,4.48,.66,16,'muted')
    foot(s, 'Статус экспериментальной кампании — PARTIAL; пропуски, таймауты и отрицательные результаты раскрыты.', link=REPORT)

    s = base('Приложение B / Методика', 'Что означает показатель 74,73 секунды',
             note='Отвечая на вопрос о скорости, назвать модель, метрику, среду и ограничения. Показатель не включает валидацию, но включает полный вывод расписания. Не переносить его на совместные ограничения или на промышленный объект. Все результаты повторов и качество опубликованы.', sources=[REPORT, ROOT+'/blob/main/docs/results/revision-v2/final/APS_MATRIX_REPORT_RU.md'])
    card(s,.7,2.67,7.05,3.95,'Что измеряли','10 уникальных входов × 3 повтора на каждом из двух размеров: 100 тысяч и миллион операций.\n\n74,73 с — максимум медиан для миллиона.','ВХОД И СТАТИСТИКА')
    card(s,8.2,2.67,7.05,3.95,'Что входит во время','Запуск процесса, чтение входа, назначения, очереди и полный вывод.\n\nPython 3.12 · 1 CPU · 4 GiB · GitHub Actions.','УСЛОВИЯ')
    text(s,'Допустимость всех планов проверена отдельно. Оптимальность не заявляется.',.8,7.02,14.4,.54,24,'teal',True)
    foot(s,'APS-BASIC: поступления, предшествования, альтернативные станки; без конечных буферов и общих ресурсов.',link=REPORT)

    s = base('Приложение C / Результаты исследования', 'Результаты определили границы и архитектуру продукта',
             note='Не скрывать отрицательные результаты. В F1/100k K=100 завершились 18 DES-процессов, все 18 TSFG остановлены по 300 с. Общие завершённые траектории совпали, полных пар нет; гипотеза ускорения INCONCLUSIVE. Большие входы были слабыми контролями совместной связи. Два банка рекомендаций по 1000 сценариев не прошли критерий полезности; шесть других областей не завершены/не допущены. Потоковая агрегация отдельна от точных операций.', sources=[REPORT])
    card(s,.7,2.67,4.58,4.38,'Точное исполнение','Преимущество TSFG по скорости не установлено.\n\nВ F1/100k: 18 DES завершены; 18 TSFG — таймаут 300 с.','01')
    card(s,5.71,2.67,4.58,4.38,'Усиление ресурсов','Критерий полезности рекомендаций не подтверждён.\n\nДве завершённые выборки по 1 000 сценариев.','02')
    card(s,10.72,2.67,4.58,4.38,'Потоковый TSFG','Шесть диагностик точности прошли проверку.\n\nСкорость агрегации и случайные риски не измерены.','03')
    foot(s,'Эти результаты сохраняются в отчёте. Автоматический выбор лучшего усиления не входит в подтверждённое обещание.',link=REPORT)

    s = base('Приложение D / Источники', 'Проверяемые основания презентации',
             note='Все ссылки кликабельны в PPTX и PDF. Материалы программы и поставщика проверены 27 сентября 2026. Данные о команде запросили у пользователя; публичную принадлежность к организации не утверждаем.', sources=[PROGRAM,REPORT,BFG,ROOT+'/releases/tag/revision-v2-final-package-16366e27dea4'])
    sources = [('01','Программа акселератора','Фокус на инженерном заделе и маршруте внедрения в ТЭК.',PROGRAM),('02','Экспериментальный отчёт Sheaft v2.2','Методика, результаты, ограничения и отрицательные наблюдения.',REPORT),('03','Публичный архив данных','Реестр входов, версий, хешей и сохранённых результатов.',ROOT+'/releases/tag/revision-v2-final-package-16366e27dea4'),('04','BFG APS — показатель поставщика','Миллион операций за 45 минут; условия не выровнены с Sheaft.',BFG)]
    for i,(n,title,desc,url) in enumerate(sources):
        y=2.55+i*1.18
        text(s,n,.8,y,.75,.4,22,'teal',True)
        text(s,title,1.87,y,12.85,.49,24,'teal',True,link=url)
        text(s,desc,1.87,y+.6,12.85,.43,18,'muted')
    foot(s,'Подготовлено 27 сентября 2026 · 12 основных слайдов + 4 слайда для вопросов экспертов.')

    prs.save(OUT / f'{STEM}.pptx')
    (OUT/'deck-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    notes = ['# Sheaft — заметки докладчика\n\nОсновная часть: 12 слайдов, ориентир 5–7 минут. Приложение — для вопросов.\n']
    for item in manifest:
        notes.append(f"## {item['number']:02}. {item['title']}\n\n{item['notes']}\n\n" + '\n'.join(f'- {u}' for u in item['sources']))
    (OUT/'Заметки_докладчика_RU.md').write_text('\n\n'.join(notes),encoding='utf-8')
    print(json.dumps(dict(status='BUILT',slides=len(prs.slides)),ensure_ascii=False))


def normalized(value):
    return re.sub(r'\s+', '', value).replace('\u00ad','').replace('−','-')


def verify():
    import fitz
    data=json.loads((OUT/'deck-manifest.json').read_text(encoding='utf-8'))
    doc=fitz.open(OUT/f'{STEM}.pdf')
    assert len(doc)==len(data)==16
    issues=[]
    thumbs=[]
    previews=OUT/'previews';previews.mkdir(exist_ok=True)
    for i,page in enumerate(doc):
        content=normalized(page.get_text())
        for expected in data[i]['texts']:
            if normalized(expected) not in content:
                issues.append(dict(slide=i+1,kind='text_missing_or_interrupted',text=expected))
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines',[]):
                for span in l.get('spans',[]):
                    x0,y0,x1,y1=span['bbox']
                    if min(x0,y0)<-.5 or x1>page.rect.width+.5 or y1>page.rect.height+.5:
                        issues.append(dict(slide=i+1,kind='text_outside_page',text=span['text']))
        pix=page.get_pixmap(matrix=fitz.Matrix(1,1),alpha=False)
        pix.save(str(previews/f'slide-{i+1:02}.png'))
        im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        im.thumbnail((480,270))
        thumbs.append(im)
    sheet=Image.new('RGB',(4*500,4*304),(224,230,226))
    draw=ImageDraw.Draw(sheet)
    for i,im in enumerate(thumbs):
        x=(i%4)*500+10;y=(i//4)*304+10
        sheet.paste(im,(x,y))
        draw.text((x,y+275),f'{i+1:02}',fill=(16,40,49))
    sheet.save(OUT/'Обзор_слайдов.png')
    result=dict(status='PASS' if not issues else 'FAIL',slides=len(doc),issues=issues,
                source_commit=os.environ.get('GITHUB_SHA'),run_id=os.environ.get('GITHUB_RUN_ID'))
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='SHA256.json'}
    (OUT/'SHA256.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if issues:raise SystemExit(1)


if __name__=='__main__':
    verify() if '--verify' in sys.argv else build()
