# История приёмки

Все указанные исполнения — GitHub-hosted Actions. Неуспешные попытки сохранены.

| Run | Содержание | Итог |
|---|---|---|
| [36228034033](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36228034033) | Фиксация окружения, Mk01 и JSON-заголовка | PASS |
| [36228702414](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36228702414) | E0 самостоятельного GRID, DES/DAG/SimPy | PASS; не приёмка исходного TSFG |
| [36229284418](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36229284418) | Первое подключение закрытого S1 | FAIL: SSH-аутентификация; моделирование не началось |
| [36229821826](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36229821826) | Исправлен формат существующего ключа; 157 тестов S1 и E0 с адаптером | PASS |
| [36230125852](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36230125852) | Первая полная серия Mk01 | PASS |
| [36230395401](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36230395401) | Окончательная приёмка с проверкой JSON-контрактов | PASS; источник опубликованного архива |

Основной исполняемый код приёмки: commit
`75776d6c81806fdd2a53c8faf95e8283ef2409f6`. Позднейшие изменения публикации добавляют
документацию и точные копии артефактов; они не подменяют результаты новым запуском.

Код исходного S1 не менялся. Публичный адаптер, исходное ядро и собранный бинарник
идентифицированы в `docs/results/mk01/tsfg-provenance.json`. Архив включает
полные входы и результаты; частный исходник и его Go-бинарник исключены.

## Последующие допуски и аудиты

| Run | Содержание | Итог |
|---|---|---|
| [36232181823](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36232181823) | Первая масштабная калибровка, seed901 | PASS; не H3 |
| [36233184981](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36233184981) | E1X: буферы, дополнительный ресурс, дробные скорости | PASS |
| [36233185095](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36233185095) | Воспроизведение исходного Ozon и аудит адаптера | PASS |
| [36233867001](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36233867001) | Первая попытка парного аудита | FAIL: проверка владельца Git checkout, до замеров |
| [36234360859](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36234360859) | Парный аудит до/после исправления | PASS; 2000 совпавших траекторий, сокращение времени 31–32% |
| [36234413565](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36234413565) | 48 наборов E2, K=10 | 140 полных корректных процессов, 4 TIMEOUT |
| [36234852274](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36234852274) | E4: ранжирование и независимые вмешательства | Проверки PASS; H5 NOT_SUPPORTED |
| [36247684531](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36247684531) | Первое ранжирование G2 v1 | Историческая версия; после численного аудита повторена |
| [36248742380](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36248742380) | 36 полных MISSION-состояний на миллионных входах | PASS |
| [36251071943](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36251071943) | Численная регрессия G2 v1/v2 | Дефект v1 воспроизведён; исправление v2 PASS |
| [36251306989](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36251306989) | Повтор ранжирования G2 v2 | PASS; F1 top-3 overlap=3, F2 overlap=0 |
| [36252103124](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36252103124) | Интерпретация счётчика пиковой памяти | Влияние истории fork/exec подтверждено; изолированное сравнение памяти UNSUPPORTED |
| [36251407245](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36251407245) | Сборка предварительного PDF по реальным артефактам | PASS; предварительный отчёт отклоняется финальным барьером публикации |

Основная E2 остаётся закреплена на afb7081. Исправленные E3 и ранжирование,
первоначальная E3 с известным численным дефектом и контрольные аудиты перечислены
в `provenance/campaign.json`. Успех workflow означает успешное выполнение
его проверок, а не автоматическое подтверждение исследовательской гипотезы.

## Завершение полной кампании, 27 сентября 2026

| Run | Содержание | Итог |
|---|---|---|
| [36247215750](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36247215750) | Полная основная E2, самостоятельные K=100 | 72/72 блока измерены и независимо проверены; 336 корректных полных процессов, 96 TIMEOUT; H3: 4 NOT_SUPPORTED, 12 INSUFFICIENT_COMPLETED |
| [36247161084](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36247161084) | Историческая E3 v1 | Выполнена; известный численный дефект сохранён, не используется вместо исправленной серии |
| [36251242869](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36251242869) | Все 48 наборов E3 v2 | Исполнения PASS; 6/48 наборов допущены по MISSION, 0/48 по DIAGNOSTIC |
| [36247446499](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36247446499) | 57 дополнительных наборов | 160 корректных полных процессов, 11 TIMEOUT |
| [36288237817](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36288237817) | Полный отчёт, данные и контрольные суммы | PASS; окончательные документы созданы из закреплённых свидетельств на commit 3ceb916 |
| [36288868044](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36288868044) | Первая публикация итогового отчёта | FAIL после проверки архива и создания пустого черновика: endpoint поиска опубликованного релиза по тегу не вернул черновик; результаты не изменялись |
| [36297561629](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36297561629) | Проверки исправленного издателя | PASS; поиск черновика заменён на аутентифицированный список релизов |
| [36297674896](https://github.com/a-a-k/sheaft-tsfg-experiments/actions/runs/36297674896) | Повтор публикации неизменённого итогового артефакта | PASS; 20 файлов, все SHA-256 загрузки совпали; релиз опубликован 27 сентября в 05:36 UTC |

Итоговые PDF, MD, JSON, CSV и PNG в `docs/results/full-study` — точные копии файлов
из Actions 36288237817. PDF и архивы исходных данных и свидетельств доступны
в [релизе v0.2.0-full-study](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/v0.2.0-full-study).
Раздел о продукте на DAG включён в окончательный отчёт.
