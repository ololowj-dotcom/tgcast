tgcast for Windows  /  tgcast для Windows
=========================================

ENGLISH
-------
tgcast posts one message to a list (a "base") of your Telegram chats, from your
Telegram account, slowly and within limits. Use it for chats you run or are
allowed to post in.

1. Create an empty folder for one mailing, for example  C:\tgcast\my-mailing
   and copy tgcast.exe into it.
2. Double-click tgcast.exe. A menu opens.
3. Type 1 and press Enter: first-time setup. It asks for your api_id and
   api_hash (get them once at https://my.telegram.org -> API development tools),
   your phone number (+...), and the login code that Telegram sends you inside
   the Telegram app. It then creates these files next to tgcast.exe:
     message.md    your text (edit it in Notepad)
     targets.txt   your chats, one per line: @username, t.me link or chat id
     tgcast.toml   settings (limits, pauses)
4. Edit message.md and targets.txt, save them.
5. In the menu: 2 = check which chats you can post to, 3 = preview (nothing is
   sent), 4 = send (asks you to confirm first).

Keep tgcast.session and .env private: tgcast.session is your Telegram login.
Full guide: https://github.com/ololowj-dotcom/tgcast

"Windows protected your PC" (SmartScreen) can appear because the program is not
digitally signed. Click "More info" -> "Run anyway". To be sure the file is the
one built by GitHub, compare its checksum with SHA256SUMS.txt:
  certutil -hashfile tgcast-windows.zip SHA256


РУССКИЙ
-------
tgcast публикует одно сообщение в список (базу) ваших Telegram-чатов от вашего
Telegram-аккаунта, неторопливо и в рамках лимитов. Используйте его для чатов,
которые вы ведёте или где вам разрешено писать.

1. Создайте пустую папку под одну рассылку, например  C:\tgcast\my-mailing
   и скопируйте в неё tgcast.exe.
2. Дважды щёлкните по tgcast.exe. Откроется меню.
3. Введите 1 и нажмите Enter: первая настройка. Программа спросит api_id и
   api_hash (получаются один раз на https://my.telegram.org -> API development
   tools), номер телефона (+...) и код входа, который Telegram пришлёт вам в
   приложении Telegram. Затем рядом с tgcast.exe появятся файлы:
     message.md    ваш текст (правится в Блокноте)
     targets.txt   ваши чаты, по одному на строку: @username, ссылка t.me или id
     tgcast.toml   настройки (лимиты, паузы)
4. Отредактируйте message.md и targets.txt и сохраните.
5. В меню: 2 = проверить, в какие чаты можно писать, 3 = предпросмотр (ничего не
   отправляется), 4 = отправить (сначала попросит подтверждение).

Файлы tgcast.session и .env никому не показывайте: tgcast.session - это вход в
ваш Telegram. Полная инструкция: https://github.com/ololowj-dotcom/tgcast

Может появиться окно «Windows защитил ваш компьютер» (SmartScreen), потому что
программа не имеет цифровой подписи. Нажмите «Подробнее» -> «Выполнить в любом
случае». Чтобы убедиться, что файл собран именно GitHub, сравните контрольную
сумму с SHA256SUMS.txt:
  certutil -hashfile tgcast-windows.zip SHA256
