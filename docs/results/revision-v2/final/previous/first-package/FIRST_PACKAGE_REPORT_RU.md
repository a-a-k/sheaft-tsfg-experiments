# Первый пакет Sheaft v2.2

**Первый пакет обработан полностью. Общая кампания остаётся PARTIAL.**

E4 сохранена в [долговременном архиве](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/revision-v2-e4-1bab7db283f5). Повторный анализ выпуска выполнен без моделирования; прежняя H5 не пересматривается.

APS: 30 валидных измерений на 100 тысячах операций и первые два миллионных плана опубликованы в [отдельном отчёте и архиве](https://github.com/a-a-k/sheaft-tsfg-experiments/releases/tag/revision-v2-aps-first-c2c51bbdecce). Полная APS-матрица выполняется отдельно.

PBR: ручные случаи, прежняя регрессия, 135 комбинированных сценариев Mk01 и 405 проверок состояния к сроку прошли сопоставление Fraction / DES-EXT / оригинального S1 с адаптером.

Обработаны все 36 предварительных экземпляров. K=10 выполнено и сопоставлено для 30; у 6 доказана номинальная взаимная блокировка. Для них K=10 не запускалось: это NO_ADMISSIBLE_INPUT, а не нулевое время или неудачный отказной сценарий. Оба движка согласны по индивидуальным состояниям; очереди не заменялись.

Сильных контролей: 1; слабых: 29. Сильный контроль требует одновременно ожидания ресурса, удержания станка после обработки и прослеженной связи между ними. Ёмкости и seed после просмотра результатов не менялись.

| Вход | K10 | Класс контроля | TSFG, с | DES, с |
|---|---|---|---:|---:|
| F1-DENSE-N1000-M200-s101-PB | COMPLETE_VALID | WEAK_CONTROL | 6.878 | 0.021 |
| F1-DENSE-N1000-M200-s101-PBR | COMPLETE_VALID | WEAK_CONTROL | 9.102 | 0.042 |
| F1-DENSE-N1000-M200-s101-PR | COMPLETE_VALID | WEAK_CONTROL | 9.045 | 0.041 |
| F1-DENSE-N1000-M200-s102-PB | COMPLETE_VALID | WEAK_CONTROL | 4.569 | 0.022 |
| F1-DENSE-N1000-M200-s102-PBR | COMPLETE_VALID | WEAK_CONTROL | 6.905 | 0.021 |
| F1-DENSE-N1000-M200-s102-PR | COMPLETE_VALID | WEAK_CONTROL | 9.177 | 0.042 |
| F1-DENSE-N1000-M200-s103-PB | COMPLETE_VALID | WEAK_CONTROL | 5.208 | 0.021 |
| F1-DENSE-N1000-M200-s103-PBR | COMPLETE_VALID | WEAK_CONTROL | 4.981 | 0.020 |
| F1-DENSE-N1000-M200-s103-PR | COMPLETE_VALID | WEAK_CONTROL | 9.208 | 0.042 |
| F2-DENSE-N1000-M200-s101-PB | COMPLETE_VALID | WEAK_CONTROL | 3.481 | 0.041 |
| F2-DENSE-N1000-M200-s101-PBR | COMPLETE_VALID | WEAK_CONTROL | 3.264 | 0.022 |
| F2-DENSE-N1000-M200-s101-PR | COMPLETE_VALID | WEAK_CONTROL | 6.294 | 0.042 |
| F2-DENSE-N1000-M200-s102-PB | COMPLETE_VALID | WEAK_CONTROL | 5.471 | 0.041 |
| F2-DENSE-N1000-M200-s102-PBR | COMPLETE_VALID | WEAK_CONTROL | 6.050 | 0.041 |
| F2-DENSE-N1000-M200-s102-PR | COMPLETE_VALID | WEAK_CONTROL | 4.517 | 0.042 |
| F2-DENSE-N1000-M200-s103-PB | COMPLETE_VALID | WEAK_CONTROL | 3.224 | 0.022 |
| F2-DENSE-N1000-M200-s103-PBR | COMPLETE_VALID | STRONG_CONTROL | 6.266 | 0.042 |
| F2-DENSE-N1000-M200-s103-PR | COMPLETE_VALID | WEAK_CONTROL | 6.093 | 0.042 |
| F1-DENSE-N10000-M200-s101-PB | COMPLETE_VALID | WEAK_CONTROL | 30.735 | 0.163 |
| F1-DENSE-N10000-M200-s101-PBR | COMPLETE_VALID | WEAK_CONTROL | 37.313 | 0.223 |
| F1-DENSE-N10000-M200-s101-PR | COMPLETE_VALID | WEAK_CONTROL | 38.123 | 0.204 |
| F1-DENSE-N10000-M200-s102-PB | COMPLETE_VALID | WEAK_CONTROL | 35.072 | 0.163 |
| F1-DENSE-N10000-M200-s102-PBR | COMPLETE_VALID | WEAK_CONTROL | 37.029 | 0.225 |
| F1-DENSE-N10000-M200-s102-PR | COMPLETE_VALID | WEAK_CONTROL | 37.998 | 0.224 |
| F1-DENSE-N10000-M200-s103-PB | COMPLETE_VALID | WEAK_CONTROL | 35.957 | 0.185 |
| F1-DENSE-N10000-M200-s103-PBR | COMPLETE_VALID | WEAK_CONTROL | 27.666 | 0.184 |
| F1-DENSE-N10000-M200-s103-PR | COMPLETE_VALID | WEAK_CONTROL | 20.933 | 0.143 |
| F2-DENSE-N10000-M200-s101-PB | NOT_RUN_NO_ADMISSIBLE_BASELINE | NO_ADMISSIBLE_INPUT | — | — |
| F2-DENSE-N10000-M200-s101-PBR | NOT_RUN_NO_ADMISSIBLE_BASELINE | NO_ADMISSIBLE_INPUT | — | — |
| F2-DENSE-N10000-M200-s101-PR | COMPLETE_VALID | WEAK_CONTROL | 25.711 | 0.244 |
| F2-DENSE-N10000-M200-s102-PB | NOT_RUN_NO_ADMISSIBLE_BASELINE | NO_ADMISSIBLE_INPUT | — | — |
| F2-DENSE-N10000-M200-s102-PBR | NOT_RUN_NO_ADMISSIBLE_BASELINE | NO_ADMISSIBLE_INPUT | — | — |
| F2-DENSE-N10000-M200-s102-PR | COMPLETE_VALID | WEAK_CONTROL | 19.510 | 0.205 |
| F2-DENSE-N10000-M200-s103-PB | NOT_RUN_NO_ADMISSIBLE_BASELINE | NO_ADMISSIBLE_INPUT | — | — |
| F2-DENSE-N10000-M200-s103-PBR | NOT_RUN_NO_ADMISSIBLE_BASELINE | NO_ADMISSIBLE_INPUT | — | — |
| F2-DENSE-N10000-M200-s103-PR | COMPLETE_VALID | WEAK_CONTROL | 24.674 | 0.244 |

Это предварительные измерения на разных VM. Внешний таймер опрашивает процесс с периодом 20 мс; для коротких DES-процессов эта дискретность заметна. Их нельзя использовать как точный парный коэффициент. В основных больших парных опытах используется уведомление Linux pidfd без такой дискретности.

F1/DENSE с разными исходными seed может иметь одинаковую семантику: совпадения хешей публикуются. Три обозначения seed сами по себе не доказывают разнообразие производственных входов.

PF: после исправления масштаба времени шесть фиксированных непрерывных потоковых случаев прошли допуск, ложных успехов на детерминированной сетке нет. Первый запуск фактически использовал шаг 0,1 с вместо 0,005 с; его артефакты сохранены как ошибка реализации шага. Исправленный запуск проверяет фактический шаг каждого вызова S1. Это не доказательство точности дискретного производства и не замер ускорения.

Ограничение продукта: быстрый APS-BASIC строит план для своей постановки, но его фиксированные очереди могут оказаться невыполнимыми при добавлении конечных буферов. Проверка исполнения и построение плана с учётом этих ограничений остаются разными функциями. DAG сохраняет область применения прежней модели.
