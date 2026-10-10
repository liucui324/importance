# -*- coding: utf-8 -*-
"""生活记录系统：睡觉 / 糖分 / 学习 / 厕所 / 运动记录"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from flask import Flask, flash, g, redirect, render_template, request, url_for

DT_FMT = "%Y-%m-%dT%H:%M"   # <input type="datetime-local"> 提交格式
DATE_FMT = "%Y-%m-%d"

# 常见含糖食物/饮品的每份参考含糖量（克）。仅为常见估值，可在表单中修改
SUGAR_PRESETS = [
    {"item": "蛋挞",   "grams": 20, "unit": "个"},
    {"item": "月饼",   "grams": 45, "unit": "块(100g)"},
    {"item": "奶茶",   "grams": 50, "unit": "中杯(全糖)"},
    {"item": "蛋糕",   "grams": 30, "unit": "块"},
    {"item": "可乐",   "grams": 35, "unit": "罐(330ml)"},
    {"item": "饼干",   "grams": 15, "unit": "小包"},
    {"item": "巧克力", "grams": 22, "unit": "小块(40g)"},
    {"item": "冰淇淋", "grams": 20, "unit": "个"},
    {"item": "糖果",   "grams": 5,  "unit": "颗"},
    {"item": "甜甜圈", "grams": 12, "unit": "个"},
    {"item": "含糖酸奶", "grams": 15, "unit": "杯"},
    {"item": "果汁",   "grams": 30, "unit": "杯(300ml)"},
]

# 数据库文件固定放在 app.py 同级目录，避免工作目录不同导致连错库
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "life_records.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "life-record-secret-key"


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
def get_db():
    """每个请求复用同一个连接"""
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def db_cursor(commit=False):
    """供请求外（如初始化）使用的游标上下文管理器"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """创建全部数据表（已存在则跳过）"""
    with db_cursor(commit=True) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sleep_records (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,          -- 入睡时间 YYYY-MM-DD HH:MM
                end_time   TEXT NOT NULL,          -- 起床时间 YYYY-MM-DD HH:MM
                note       TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS sugar_records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL,         -- 记录日期 YYYY-MM-DD
                item        TEXT NOT NULL,         -- 含糖食物/饮品名称
                quantity    REAL NOT NULL DEFAULT 1,   -- 份数
                sugar_grams REAL NOT NULL,         -- 该份含糖量(克)
                note        TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS study_records (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,          -- 开始学习 YYYY-MM-DD HH:MM
                end_time   TEXT NOT NULL,          -- 结束学习 YYYY-MM-DD HH:MM
                content    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS toilet_records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL,         -- 记录日期 YYYY-MM-DD
                count       INTEGER NOT NULL CHECK(count >= 0),
                note        TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS exercise_records (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,          -- 开始时间 YYYY-MM-DD HH:MM
                end_time   TEXT NOT NULL,          -- 结束时间 YYYY-MM-DD HH:MM
                content    TEXT NOT NULL,          -- 运动内容
                note       TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            """
        )


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------
def parse_dt(value):
    """把 datetime-local 字符串解析为 datetime；失败返回 None"""
    if not value:
        return None
    try:
        return datetime.strptime(value, DT_FMT)
    except (ValueError, TypeError):
        return None


def parse_date(value):
    """把 date 输入框字符串解析为 date；失败返回 None"""
    if not value:
        return None
    try:
        return datetime.strptime(value, DATE_FMT).date()
    except (ValueError, TypeError):
        return None


def format_duration(start_dt, end_dt):
    """把时间差格式化为「X小时Y分钟」，跨天睡眠同样适用"""
    total_minutes = int((end_dt - start_dt).total_seconds() // 60)
    return format_minutes(total_minutes)


def format_minutes(total_minutes):
    """把分钟数格式化为「X小时Y分钟」"""
    total_minutes = max(0, total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}小时{minutes}分钟"
    if hours:
        return f"{hours}小时"
    return f"{minutes}分钟"


def dt_display(value):
    """把库中 'YYYY-MM-DD HH:MM' 转为 'YYYY-MM-DD HH:MM'（原样，保留扩展点）"""
    return value.replace("T", " ")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """主页：仅展示四个功能入口"""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# 睡觉记录
# ---------------------------------------------------------------------------
@app.route("/sleep")
def sleep_page():
    """睡觉记录页：表单 + 历史记录（最近在前）"""
    rows = get_db().execute(
        "SELECT id, start_time, end_time, note FROM sleep_records "
        "ORDER BY start_time DESC, id DESC"
    ).fetchall()

    records = []
    for row in rows:
        start_dt = parse_dt(row["start_time"].replace(" ", "T"))
        end_dt = parse_dt(row["end_time"].replace(" ", "T"))
        duration = format_duration(start_dt, end_dt) if start_dt and end_dt else "-"
        records.append({
            "id": row["id"],
            "start_time": dt_display(row["start_time"]),
            "end_time": dt_display(row["end_time"]),
            "duration": duration,
            "note": row["note"],
        })

    return render_template("sleep.html", records=records)


@app.route("/sleep/add", methods=["POST"])
def sleep_add():
    """新增一条睡觉记录"""
    start_raw = (request.form.get("start_time") or "").strip()
    end_raw = (request.form.get("end_time") or "").strip()
    note = (request.form.get("note") or "").strip()[:200]

    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)

    if start_dt is None or end_dt is None:
        flash("请正确填写入睡时间和起床时间", "error")
    elif start_dt >= end_dt:
        flash("起床时间必须晚于入睡时间", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO sleep_records (start_time, end_time, note) VALUES (?, ?, ?)",
            (start_dt.strftime("%Y-%m-%d %H:%M"),
             end_dt.strftime("%Y-%m-%d %H:%M"), note),
        )
        db.commit()
        flash("睡觉记录已添加", "success")

    return redirect(url_for("sleep_page"))


@app.route("/sleep/delete/<int:record_id>", methods=["POST"])
def sleep_delete(record_id):
    """删除一条睡觉记录；记录不存在也不报错（幂等）"""
    db = get_db()
    db.execute("DELETE FROM sleep_records WHERE id = ?", (record_id,))
    db.commit()
    flash("记录已删除", "success")
    return redirect(url_for("sleep_page"))


# ---------------------------------------------------------------------------
# 糖分记录
# ---------------------------------------------------------------------------
def _fmt_number(value):
    """整数去 .0，非整数保留至多 1 位小数"""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


@app.route("/sugar")
def sugar_page():
    """糖分记录页：表单（含快捷选择）+ 按日期分组的历史"""
    rows = get_db().execute(
        "SELECT id, record_date, item, quantity, sugar_grams, note "
        "FROM sugar_records ORDER BY record_date DESC, id DESC"
    ).fetchall()

    # 按日期分组，并计算每日合计
    groups = []
    today_str = datetime.now().strftime(DATE_FMT)
    today_total = 0.0
    index = {}
    for row in rows:
        total = row["quantity"] * row["sugar_grams"]
        entry = {
            "id": row["id"],
            "item": row["item"],
            "quantity": _fmt_number(row["quantity"]),
            "sugar_grams": _fmt_number(row["sugar_grams"]),
            "total": _fmt_number(total),
            "note": row["note"],
        }
        if row["record_date"] not in index:
            group = {"date": row["record_date"], "entries": [], "day_total": 0.0}
            index[row["record_date"]] = group
            groups.append(group)
        index[row["record_date"]]["entries"].append(entry)
        index[row["record_date"]]["day_total"] += total
        if row["record_date"] == today_str:
            today_total += total

    for group in groups:
        group["day_total"] = _fmt_number(group["day_total"])

    # --- 本月糖分汇总 ---
    now = datetime.now()
    month_prefix = now.strftime("%Y-%m")          # 如 "2026-10"
    month_total = 0.0
    for row in rows:
        if row["record_date"].startswith(month_prefix):
            month_total += row["quantity"] * row["sugar_grams"]

    # 日均 = 本月总量 / 本月已过天数（至少 1 天）
    days_elapsed = max(1, now.day)
    month_daily_avg = month_total / days_elapsed

    # 提醒等级（参考 WHO 建议每日添加糖 < 25g 为宜，≤50g 为上限）
    if month_daily_avg < 25:
        month_reminder = "糖分摄入正常，继续保持"
        month_level = "ok"
    elif month_daily_avg <= 50:
        month_reminder = "糖分摄入偏高，建议适当控制"
        month_level = "warn"
    else:
        month_reminder = "糖分摄入过高，建议减少甜食"
        month_level = "alert"

    return render_template(
        "sugar.html",
        presets=SUGAR_PRESETS,
        groups=groups,
        today_total=_fmt_number(today_total),
        today=today_str,
        month_total=_fmt_number(month_total),
        month_daily_avg=_fmt_number(month_daily_avg),
        month_label=f"{now.year}年{now.month}月",
        month_reminder=month_reminder,
        month_level=month_level,
    )


@app.route("/sugar/add", methods=["POST"])
def sugar_add():
    """新增一条糖分记录"""
    date_raw = (request.form.get("record_date") or "").strip()
    item = (request.form.get("item") or "").strip()[:50]
    note = (request.form.get("note") or "").strip()[:200]

    record_date = parse_date(date_raw)

    # 每份含糖量
    try:
        sugar_grams = float(request.form.get("sugar_grams"))
    except (TypeError, ValueError):
        sugar_grams = None

    # 份数（允许半份）
    try:
        quantity = float(request.form.get("quantity"))
    except (TypeError, ValueError):
        quantity = None

    if record_date is None:
        flash("请选择正确的日期", "error")
    elif not item:
        flash("请填写或选择食物/饮品名称", "error")
    elif sugar_grams is None or sugar_grams < 0:
        flash("每份含糖量必须是不小于 0 的数字", "error")
    elif quantity is None or quantity <= 0:
        flash("份数必须是大于 0 的数字", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO sugar_records (record_date, item, quantity, sugar_grams, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (record_date.strftime(DATE_FMT), item, quantity, sugar_grams, note),
        )
        db.commit()
        flash("糖分记录已添加", "success")

    return redirect(url_for("sugar_page"))


@app.route("/sugar/delete/<int:record_id>", methods=["POST"])
def sugar_delete(record_id):
    """删除一条糖分记录；记录不存在也不报错（幂等）"""
    db = get_db()
    db.execute("DELETE FROM sugar_records WHERE id = ?", (record_id,))
    db.commit()
    flash("记录已删除", "success")
    return redirect(url_for("sugar_page"))


# ---------------------------------------------------------------------------
# 学习记录
# ---------------------------------------------------------------------------
@app.route("/study")
def study_page():
    """学习记录页：表单 + 历史记录（最近在前）"""
    rows = get_db().execute(
        "SELECT id, start_time, end_time, content FROM study_records "
        "ORDER BY start_time DESC, id DESC"
    ).fetchall()

    records = []
    for row in rows:
        start_dt = parse_dt(row["start_time"].replace(" ", "T"))
        end_dt = parse_dt(row["end_time"].replace(" ", "T"))
        duration = format_duration(start_dt, end_dt) if start_dt and end_dt else "-"
        records.append({
            "id": row["id"],
            "start_time": dt_display(row["start_time"]),
            "end_time": dt_display(row["end_time"]),
            "duration": duration,
            "content": row["content"],
        })

    # 今日累计学习时长（基于开始时间为今天的记录）
    today_str = datetime.now().strftime(DATE_FMT)
    study_today_minutes = 0
    for row in rows:
        if row["start_time"].startswith(today_str):
            s = parse_dt(row["start_time"].replace(" ", "T"))
            e = parse_dt(row["end_time"].replace(" ", "T"))
            if s and e:
                study_today_minutes += int((e - s).total_seconds() // 60)

    return render_template(
        "study.html",
        records=records,
        today_total=format_minutes(study_today_minutes),
    )


@app.route("/study/add", methods=["POST"])
def study_add():
    """新增一条学习记录"""
    start_raw = (request.form.get("start_time") or "").strip()
    end_raw = (request.form.get("end_time") or "").strip()
    content = (request.form.get("content") or "").strip()[:300]

    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)

    if start_dt is None or end_dt is None:
        flash("请正确填写开始时间和结束时间", "error")
    elif start_dt >= end_dt:
        flash("结束时间必须晚于开始时间", "error")
    elif not content:
        flash("请填写学习内容", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO study_records (start_time, end_time, content) "
            "VALUES (?, ?, ?)",
            (start_dt.strftime("%Y-%m-%d %H:%M"),
             end_dt.strftime("%Y-%m-%d %H:%M"), content),
        )
        db.commit()
        flash("学习记录已添加", "success")

    return redirect(url_for("study_page"))


@app.route("/study/delete/<int:record_id>", methods=["POST"])
def study_delete(record_id):
    """删除一条学习记录；记录不存在也不报错（幂等）"""
    db = get_db()
    db.execute("DELETE FROM study_records WHERE id = ?", (record_id,))
    db.commit()
    flash("记录已删除", "success")
    return redirect(url_for("study_page"))


# ---------------------------------------------------------------------------
# 厕所记录
# ---------------------------------------------------------------------------
@app.route("/toilet")
def toilet_page():
    """厕所记录页：今日次数卡片 + 表单 + 历史记录"""
    rows = get_db().execute(
        "SELECT id, record_date, count, note FROM toilet_records "
        "ORDER BY record_date DESC, id DESC"
    ).fetchall()

    today_str = datetime.now().strftime(DATE_FMT)
    today_count = 0
    records = []
    for row in rows:
        records.append({
            "id": row["id"],
            "record_date": row["record_date"],
            "count": row["count"],
            "note": row["note"],
        })
        if row["record_date"] == today_str:
            today_count += row["count"]

    return render_template(
        "toilet.html",
        records=records,
        today_count=today_count,
        today=today_str,
    )


@app.route("/toilet/add", methods=["POST"])
def toilet_add():
    """新增一条厕所记录（次数为正整数）"""
    date_raw = (request.form.get("record_date") or "").strip()
    note = (request.form.get("note") or "").strip()[:200]
    record_date = parse_date(date_raw)

    # 次数：必须是整数且 >= 1
    count_raw = request.form.get("count")
    try:
        count = int(count_raw)
        is_integer_value = float(count_raw).is_integer()
    except (TypeError, ValueError):
        count = None
        is_integer_value = False

    if record_date is None:
        flash("请选择正确的日期", "error")
    elif count is None or not is_integer_value or count < 1:
        flash("次数必须是不小于 1 的整数", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO toilet_records (record_date, count, note) VALUES (?, ?, ?)",
            (record_date.strftime(DATE_FMT), count, note),
        )
        db.commit()
        flash("厕所记录已添加", "success")

    return redirect(url_for("toilet_page"))


@app.route("/toilet/quick", methods=["POST"])
def toilet_quick():
    """快速记一次：日期=今天，次数=1"""
    today_str = datetime.now().strftime(DATE_FMT)
    db = get_db()
    db.execute(
        "INSERT INTO toilet_records (record_date, count, note) VALUES (?, 1, '')",
        (today_str,),
    )
    db.commit()
    flash("已快速记录 1 次", "success")
    return redirect(url_for("toilet_page"))


@app.route("/toilet/delete/<int:record_id>", methods=["POST"])
def toilet_delete(record_id):
    """删除一条厕所记录；记录不存在也不报错（幂等）"""
    db = get_db()
    db.execute("DELETE FROM toilet_records WHERE id = ?", (record_id,))
    db.commit()
    flash("记录已删除", "success")
    return redirect(url_for("toilet_page"))


# ---------------------------------------------------------------------------
# 运动记录
# ---------------------------------------------------------------------------
@app.route("/exercise")
def exercise_page():
    """运动记录页：今日运动时长卡片 + 表单 + 历史记录"""
    rows = get_db().execute(
        "SELECT id, start_time, end_time, content, note FROM exercise_records "
        "ORDER BY start_time DESC, id DESC"
    ).fetchall()

    records = []
    for row in rows:
        start_dt = parse_dt(row["start_time"].replace(" ", "T"))
        end_dt = parse_dt(row["end_time"].replace(" ", "T"))
        duration = format_duration(start_dt, end_dt) if start_dt and end_dt else "-"
        records.append({
            "id": row["id"],
            "start_time": dt_display(row["start_time"]),
            "end_time": dt_display(row["end_time"]),
            "duration": duration,
            "content": row["content"],
            "note": row["note"],
        })

    # 今日累计运动时长（基于开始时间为今天的记录）
    today_str = datetime.now().strftime(DATE_FMT)
    exercise_today_minutes = 0
    for row in rows:
        if row["start_time"].startswith(today_str):
            s = parse_dt(row["start_time"].replace(" ", "T"))
            e = parse_dt(row["end_time"].replace(" ", "T"))
            if s and e:
                exercise_today_minutes += int((e - s).total_seconds() // 60)

    return render_template(
        "exercise.html",
        records=records,
        today_total=format_minutes(exercise_today_minutes),
    )


@app.route("/exercise/add", methods=["POST"])
def exercise_add():
    """新增一条运动记录"""
    start_raw = (request.form.get("start_time") or "").strip()
    end_raw = (request.form.get("end_time") or "").strip()
    content = (request.form.get("content") or "").strip()[:300]
    note = (request.form.get("note") or "").strip()[:200]

    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)

    if start_dt is None or end_dt is None:
        flash("请正确填写开始时间和结束时间", "error")
    elif start_dt >= end_dt:
        flash("结束时间必须晚于开始时间", "error")
    elif not content:
        flash("请填写运动内容", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO exercise_records (start_time, end_time, content, note) "
            "VALUES (?, ?, ?, ?)",
            (start_dt.strftime("%Y-%m-%d %H:%M"),
             end_dt.strftime("%Y-%m-%d %H:%M"), content, note),
        )
        db.commit()
        flash("运动记录已添加", "success")

    return redirect(url_for("exercise_page"))


@app.route("/exercise/delete/<int:record_id>", methods=["POST"])
def exercise_delete(record_id):
    """删除一条运动记录；记录不存在也不报错（幂等）"""
    db = get_db()
    db.execute("DELETE FROM exercise_records WHERE id = ?", (record_id,))
    db.commit()
    flash("记录已删除", "success")
    return redirect(url_for("exercise_page"))


if __name__ == "__main__":
    init_db()
    # host=0.0.0.0 方便手机通过局域网 IP 访问。
    # 关闭 watchdog 重载器：Windows 上它的父子进程容易残留/卡死且占用端口；
    # 单进程更稳定，改动代码后手动重启即可。
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=False,
    )
