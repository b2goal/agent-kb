# agent-kb

Kho tri thức và telemetry cho coding agent, **độc lập với harness**. Bản v0.1 hỗ trợ Claude Code; Codex và Antigravity sẽ thêm bằng adapter. Mọi lệnh `kb` là code thuần, không gọi model, nên không tốn token.

## Cài

```bash
uv tool install git+https://github.com/<bạn>/agent-kb     # hoặc: pipx install git+...
kb setup claude        # gắn hook + status line vào ~/.claude/settings.json (có sao lưu)
kb doctor
```

Chạy từ mã nguồn: `pip install -e .` hoặc `python -m agent_kb ...`. Cần Python ≥3.9 và git. Không cần thư viện ngoài.

## Dùng hằng ngày

| Lệnh | Việc |
|---|---|
| (tự động) | Hook ghi mỗi tool call; khi session kết thúc thì đọc transcript vào telemetry |
| status line | `kb 142 tool · lỗi 4% · chặn 3 · ⚠ 2 điều kiện, chạy: kb tune` |
| `kb stats [--days 7]` | Thống kê project hiện tại: lượt, token, cache, lệnh bị chặn, lỗi lặp lại, browser |
| `kb tune` | Đánh giá điều kiện, ghi đề xuất vào outbox |
| `kb tune --apply latest --select 1,3` | Áp dụng đề xuất đã chọn: allow-list vào `.claude/settings.local.json`, hướng dẫn vào khối quản lý trong `CLAUDE.md`, lưu baseline |
| `kb outbox` | Đề xuất và xung đột đang chờ |
| `kb add convention <chủ đề> --body "..."` | Ghi tri thức tay (hạng tin cậy cao nhất) |
| `kb search "<chủ đề>"`, `kb get <id>` | Tìm và đọc tri thức |
| `kb confirm <id>`, `kb retire <id>` | Xác nhận (thay thế mục cũ, giải quyết xung đột) hoặc ngừng dùng |
| `kb export claude-md [--write]` | Xuất hướng dẫn cho Claude Code |
| `kb ingest [--recent N] [--force]` | Đọc lại transcript cũ (lần đầu cài) |
| `kb index rebuild` | Dựng lại index và metadata từ file |
| `kb serve` | API cục bộ 127.0.0.1:8765 (cho dashboard sau này) |

## Dữ liệu ở đâu

`~/.agent-kb/` (đổi bằng `AGENT_KB_HOME`):

- `knowledge/<project>/<kind>/<id>.md`: tri thức, nguồn gốc là file, có lịch sử
- `kb.db`: metadata, change log, xung đột (dựng lại được)
- `telemetry.db`: session và tool event (dữ liệu thô giữ 60 ngày)
- `index/`: index FTS (dựng lại được)
- `outbox/`, `baselines/`, `spool/`, `config.json`

Project được định danh bằng git remote (`github.com/cty/app`), nên cùng project trên nhiều máy khớp nhau.

## Cấu hình

`~/.agent-kb/config.json` (tạo khi `kb setup`). Các mục chính:
- `triggers`: ngưỡng kích hoạt, `mode` (`notify` chỉ báo, hoặc `background` tự ghi đề xuất vào outbox, cả hai đều 0 token)
- `rank`: thứ tự tin cậy của nguồn
- `indexes`: bật/tắt index; plugin mới khai báo bằng `"class": "module:Class"`

## Mở rộng

- **Harness mới:** thêm `agent_kb/adapters/<harness>.py` (đọc log, gắn hook) và một bộ xuất hướng dẫn.
- **Index mới** (vector, graph, reranker): lớp có `build/update/query/health`, khai báo trong `config.json`. Index lỗi hoặc chậm sẽ bị bỏ qua, FTS luôn là đường dự phòng.
- **Nguồn mới** (Confluence, Jira): ghi qua `LocalStore.put()` với `rank` của nguồn; mục kém tin cậy hơn mà mâu thuẫn sẽ thành xung đột chờ duyệt.
- **An toàn dữ liệu:** cắm hàm vào `LocalStore.write_filters` và `query.egress_filters` (hiện để trống).

## Test

```bash
python -m unittest discover -s tests -t .
```

## Start here

New session? Read `CONTEXT.md` first (goals, findings, design, next steps).
