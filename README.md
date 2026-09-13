# Felix

個人用的 TIDAL 播放後端：`tidalapi` 向 TIDAL 拿目錄與串流，`mpv` 負責出聲。目前沒有 GUI；日常操作是一個叫 **rostrum** 的指令列。

給朋友：有 Linux、TIDAL 帳號、願意在終端機打指令就能播。
給以後的自己：這不是產品，是「能聽、能獨佔 DAC、之後再接 UI」的核心。

## 這不是什麼

- 不是官方 TIDAL 客戶端，也沒有桌面／手機介面。
- 不是跨平台；假設 Linux，系統混音走 PipeWire，獨佔走 ALSA `hw:`。
- UI 刻意不在這個 repo 的範圍裡。Rostrum 只把指令譯成 Intent、把 Event 印出來。

## 需要什麼

- Python 3.11 以上
- 系統裡的 `mpv`（要能走 PipeWire / ALSA）
- 有效的 TIDAL 帳號（要聽 lossless / Max，訂閱本身也要支援）
- 可選：外接 DAC。測試時用過 Chord Qutest 這類 `hw:CARD=…,DEV=0` 裝置

Python 套件只有 `tidalapi`。`mpv` 請用發行版套件裝，不要指望 pip。

## 安裝與登入

```sh
python -m venv .venv
source .venv/bin/activate          # fish：source .venv/bin/activate.fish
pip install -e .
python scripts/login.py
```

登入是 PKCE。瀏覽器會開 TIDAL 授權頁；成功後常會停在一個 **Oops** 畫面，那是正常的。把該頁**完整網址**（含 `?code=`）貼回終端機。

工作階段存在 `~/.config/felix/session.json`（權限 600）。這是秘密，不要提交、不要傳給別人。失效時再跑一次 `login.py`。

## 日常使用

```sh
python scripts/rostrum.py
```

提示符是 `rostrum>`。輸入 `help` 看完整指令。常見流程：

```
search IVE
play 0              # 只播搜尋結果第 0 首
album 0             # 打開搜尋結果的專輯
play 3              # 從專輯第 3 首播到結尾
playlists
play 0              # 整份 playlist 進 queue
pause / next / prev
vol 40
ao exclusive 0      # 獨佔清單上的第 0 個 ALSA 裝置
ao system           # 回到 PipeWire 混音
```

編號寫 `0`、`t0`、`a0`、`p0` 都可以。`play id <track_id>` 可跳過搜尋。

其他常用：

| 指令 | 作用 |
| --- | --- |
| `add n` | 第 n 首加入 queue |
| `now` / `queue` / `status` | 現況 |
| `lyrics` / `credits` | 現正播放；也可 `lyrics 3` |
| `shuffle` / `repeat` | 切換 |
| `seek 30`、`+5`、`-5` | 跳秒 |
| `ao devices` | 列出 ALSA `hw:` 裝置 |
| `quit` | 離開並關掉 mpv |

煙霧測試（需已登入、需 mpv）：

```sh
python scripts/play_test.py
python scripts/search_test.py IVE
```

## 兩種出聲方式

設定存在 `~/.config/felix/settings.json`，重開會記得。

**system（預設）**  
mpv 交給 PipeWire（或你指定的 `ao`）。可以跟系統其他聲音共存，軟體音量有效（`vol`）。

**exclusive**  
mpv 以 ALSA exclusive 打開 `hw:CARD=…,DEV=0`，關掉 resampler 與軟體音量（鎖 100）。請用 DAC 旋鈕。進入前會把該卡從 PipeWire 放開；結束或崩潰時盡量還原。拒絕 `plughw:`，因為那條路徑會重採樣。

切換：

```
ao devices
ao exclusive 0
ao system
```

不要在 system 模式設 `ao alsa`：可能搶走 DAC mixer，把 PipeWire 音量搞壞。看到警告就改回 `ao pipewire`。

`status` 裡的 `pcm` 一行：exclusive 時 `match` 表示輸出格式對上來源；`RESAMPLE` 表示仍在重採樣，應檢查裝置與 mpv 參數。

預設音質是 Max（hi-res lossless），拿不到再退 lossless、再退 low。

## 磁碟上會出現什麼

| 路徑 | 內容 |
| --- | --- |
| `~/.config/felix/session.json` | TIDAL PKCE session |
| `~/.config/felix/settings.json` | 音量、system / exclusive、裝置 |
| `~/.config/felix/felix.log` | 輪轉 log |
| `~/.config/felix/pw_restore.json` | exclusive 時暫存的 PipeWire 還原資訊 |
| `/tmp/felix-mpv.sock` | mpv IPC |
| `/tmp/felix-*.mpd` | DASH manifest（最多留 4 份） |

## 程式怎麼切

之後若要接 UI 或改播放行為，先認這張圖：

```
scripts / rostrum / 未來的 UI
        │  Intent
        ▼
  runtime.App          ← 唯一同時碰 TIDAL 與 mpv 的地方
        │  Event
        ▼
    EventBus

tidal/     登入、目錄、歌詞／credits、把 track 收成 PlaybackSource
engine/    啟動 mpv、IPC、PCM 讀值、PipeWire 放卡／還原
domain/    Track、Intent、Event；不准 import tidalapi 或 mpv
```

`App` 有兩條 worker，避免搜尋拖到暫停：

- **transport**：play / pause / next / seek / volume / 切輸出
- **catalog**：search、開專輯／藝人／playlist、lyrics、credits

曲目快結束時會預取下一首的 stream（約 18 秒前；manifest 約 75 秒內有效）。自然播完由 transport 接手切歌，不在 mpv 幫浦執行緒做網路 I/O。

## 測試

單元測試不需要登入、也不應真的去播 TIDAL：

```sh
python -m unittest discover -s tests -v
```

`scripts/` 底下其餘檔案是手動探針：`engine_test.py` 只餵本地檔給 mpv，`resolve_test.py` / `queue_test.py` 需要 session。

## 已知邊界

- 同一個時間只該有一個 Felix：mpv socket 是固定路徑。
- exclusive 啟動失敗會退回 system，並把原因寫進 `status` 的 error。
- session 過期時指令會失敗，訊息會叫你重跑 `login.py`。
- 這是個人工具，TIDAL 條款與 `tidalapi` 的可用性都不在保證範圍。
