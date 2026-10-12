# Проверки версии 0.2

Проверены на установленной паре CachyOS/Hyprland:

- 11 hardware-independent unittest: протокол, ACK, CRC/hash/size, malformed headers,
  повтор/collision ID, ручной Enter, Backspace, EOF, path и Unicode boundaries,
  Numpad profile, RAM budget, atomic file projection, backup, symlink rejection,
  config validation, CLI error exit code.
- Компиляция всех модулей с `python -W error -m compileall`.
- Offline bootstrap в отдельном чистом venv и запуск CLI.
- `bash -n` сгенерированных системных планов обеих ролей.
- `systemd-analyze --user verify` клиентских units.
- Hyprland reload без configerrors.
- Событие виртуальной Numpad 8 → capture → подтверждение реального SSH-приёмника.
- Три снимка подряд: три delivery confirmed, затем pending=0, bytes=0.
- Один и тот же WB1 ID отправлен дважды по реальному SSH: оба ACK проверены,
  на ПК сохранён один файл.
- send-code: файл с исходным именем появился в projects; тестовый файл удалён,
  указатель последнего пользовательского кода восстановлен.
- send-answer 3 42: clock.txt содержит 03:42; reset делает его пустым.
- Искусственный SIGSTOP сервиса ввода: systemd watchdog завершил процесс,
  другой PID перезапустился в OFF. Финальные units используют SIGKILL и LimitCORE=0.

Пользователь подтвердил срабатывание физической Numpad 9; наблюдалась полная
остановка клиентских и системных endpoint units. Поведение конкретного браузерного
редактора и все остальные физические клавиши требуют отдельного ручного теста. Виртуальное событие проверяет путь compositor binding,
но не подтверждает аппаратные особенности USB-клавиатуры. Потеря питания,
исчерпание диска, зависание ядра и длительное нарушение сети не проходили
полноценную fault-injection кампанию. Термин production-ready не означает
сертификацию или гарантию обнаружения/необнаружения сторонним ПО.
