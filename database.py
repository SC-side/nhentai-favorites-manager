import sqlite3
import os
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collection.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.execute("PRAGMA journal_mode=WAL")
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print(f"Database initialized: {DB_PATH}")


def get_existing_ids():
    conn = get_conn()
    rows = conn.execute("SELECT nhentai_id FROM doujinshi").fetchall()
    conn.close()
    return {row["nhentai_id"] for row in rows}


def doujinshi_exists(nhentai_id):
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM doujinshi WHERE nhentai_id = ?", (nhentai_id,)).fetchone()
    conn.close()
    return row is not None


def insert_doujinshi(data, tags_list):
    """Insert a doujinshi and its tags.

    data: dict with keys matching doujinshi columns
    tags_list: list of dicts with keys: name, type, count
    """
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO doujinshi
               (nhentai_id, title_ja, title_en, title_pretty, media_id, cover_type,
                pages, uploaded_at, favorited_at, rating, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["nhentai_id"],
                data.get("title_ja", ""),
                data.get("title_en", ""),
                data.get("title_pretty", ""),
                data["media_id"],
                data.get("cover_type", "j"),
                data.get("pages", 0),
                data.get("uploaded_at"),
                data.get("favorited_at"),
                data.get("rating"),
                data.get("notes", ""),
            ),
        )

        for tag in tags_list:
            conn.execute(
                "INSERT OR IGNORE INTO tags (name, type, count) VALUES (?, ?, ?)",
                (tag["name"], tag["type"], tag.get("count", 0)),
            )
            # Update count if tag already exists
            conn.execute(
                "UPDATE tags SET count = ? WHERE name = ? AND type = ?",
                (tag.get("count", 0), tag["name"], tag["type"]),
            )
            tag_row = conn.execute(
                "SELECT id FROM tags WHERE name = ? AND type = ?",
                (tag["name"], tag["type"]),
            ).fetchone()
            if tag_row:
                conn.execute(
                    "INSERT OR IGNORE INTO doujinshi_tags (doujinshi_id, tag_id) VALUES (?, ?)",
                    (data["nhentai_id"], tag_row["id"]),
                )

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def get_doujinshi(page=1, per_page=24, search="", tag_ids=None, tag_type=None,
                  sort_by="favorited_at", sort_order="desc", rating_filter=None):
    """Query doujinshi with filtering, sorting, and pagination.

    Returns: (items_list, total_count)
    """
    conn = get_conn()

    # Whitelist sort columns
    valid_sorts = {"favorited_at", "uploaded_at", "pages", "rating", "nhentai_id"}
    if sort_by not in valid_sorts:
        sort_by = "favorited_at"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    where_clauses = []
    params = []

    # Text search
    if search:
        where_clauses.append(
            "(d.title_ja LIKE ? OR d.title_en LIKE ? OR d.title_pretty LIKE ? OR d.notes LIKE ?)"
        )
        like = f"%{search}%"
        params.extend([like, like, like, like])

    # Rating filter
    if rating_filter is not None:
        if rating_filter == 0:
            where_clauses.append("d.rating IS NULL")
        else:
            where_clauses.append("d.rating = ?")
            params.append(rating_filter)

    # Tag filtering (AND logic)
    tag_join = ""
    tag_having = ""
    if tag_ids:
        tag_id_list = [int(t) for t in tag_ids]
        placeholders = ",".join("?" * len(tag_id_list))
        tag_join = f" INNER JOIN doujinshi_tags dt_filter ON d.nhentai_id = dt_filter.doujinshi_id AND dt_filter.tag_id IN ({placeholders})"
        tag_having = f" HAVING COUNT(DISTINCT dt_filter.tag_id) = ?"
        params = list(tag_id_list) + params  # tag params go first for the JOIN
        # Having param goes after WHERE params
    elif tag_type:
        # Filter to only show doujinshi that have at least one tag of this type
        tag_join = " INNER JOIN doujinshi_tags dt_filter ON d.nhentai_id = dt_filter.doujinshi_id INNER JOIN tags t_filter ON dt_filter.tag_id = t_filter.id AND t_filter.type = ?"
        params = [tag_type] + params

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    # Build count query
    if tag_ids:
        count_sql = f"SELECT COUNT(*) as cnt FROM (SELECT d.nhentai_id FROM doujinshi d{tag_join}{where_sql} GROUP BY d.nhentai_id{tag_having})"
        count_params = list(params) + [len(tag_id_list)]
    elif tag_type:
        count_sql = f"SELECT COUNT(*) as cnt FROM (SELECT DISTINCT d.nhentai_id FROM doujinshi d{tag_join}{where_sql})"
        count_params = list(params)
    else:
        count_sql = f"SELECT COUNT(*) as cnt FROM doujinshi d{where_sql}"
        count_params = list(params)

    total = conn.execute(count_sql, count_params).fetchone()["cnt"]

    # Null handling for rating sort
    null_sort = ""
    if sort_by == "rating":
        null_sort = "CASE WHEN d.rating IS NULL THEN 1 ELSE 0 END, " if sort_order == "desc" else "CASE WHEN d.rating IS NULL THEN 0 ELSE 1 END, "

    # Build data query
    offset = (page - 1) * per_page
    if tag_ids:
        data_sql = f"""SELECT d.* FROM doujinshi d{tag_join}{where_sql}
                       GROUP BY d.nhentai_id{tag_having}
                       ORDER BY {null_sort}d.{sort_by} {sort_order}
                       LIMIT ? OFFSET ?"""
        data_params = list(params) + [len(tag_id_list), per_page, offset]
    elif tag_type:
        data_sql = f"""SELECT DISTINCT d.* FROM doujinshi d{tag_join}{where_sql}
                       ORDER BY {null_sort}d.{sort_by} {sort_order}
                       LIMIT ? OFFSET ?"""
        data_params = list(params) + [per_page, offset]
    else:
        data_sql = f"""SELECT d.* FROM doujinshi d{where_sql}
                       ORDER BY {null_sort}d.{sort_by} {sort_order}
                       LIMIT ? OFFSET ?"""
        data_params = list(params) + [per_page, offset]

    rows = conn.execute(data_sql, data_params).fetchall()

    # Fetch tags for each item
    items = []
    for row in rows:
        item = dict(row)
        tag_rows = conn.execute(
            """SELECT t.id, t.name, t.type, t.count
               FROM tags t
               INNER JOIN doujinshi_tags dt ON t.id = dt.tag_id
               WHERE dt.doujinshi_id = ?
               ORDER BY t.type, t.count DESC""",
            (item["nhentai_id"],),
        ).fetchall()
        item["tags"] = [dict(t) for t in tag_rows]
        items.append(item)

    conn.close()
    return items, total


def update_rating(nhentai_id, rating):
    """Update rating. rating=None means unrated."""
    conn = get_conn()
    conn.execute("UPDATE doujinshi SET rating = ? WHERE nhentai_id = ?", (rating, nhentai_id))
    conn.commit()
    conn.close()


def update_notes(nhentai_id, notes):
    conn = get_conn()
    conn.execute("UPDATE doujinshi SET notes = ? WHERE nhentai_id = ?", (notes, nhentai_id))
    conn.commit()
    conn.close()


def delete_doujinshi_batch(nhentai_ids):
    """Delete multiple works; return the list of deleted media_ids (used to clear the cover cache)."""
    if not nhentai_ids:
        return []
    conn = get_conn()
    try:
        placeholders = ",".join("?" * len(nhentai_ids))
        rows = conn.execute(
            f"SELECT media_id FROM doujinshi WHERE nhentai_id IN ({placeholders})",
            nhentai_ids,
        ).fetchall()
        media_ids = [r["media_id"] for r in rows if r["media_id"]]
        conn.execute(
            f"DELETE FROM doujinshi_tags WHERE doujinshi_id IN ({placeholders})",
            nhentai_ids,
        )
        conn.execute(
            f"DELETE FROM doujinshi WHERE nhentai_id IN ({placeholders})",
            nhentai_ids,
        )
        conn.commit()
        return media_ids
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_favorited_order(ordered_ids, base_time=None):
    """Rewrite favorited_at to match nhentai's favorites order (front = most recent, gets the largest timestamp).

    ordered_ids: nhentai_ids in favorites-page order (index 0 = top of page 1 = most recently favorited).
    The first item gets base_time, each subsequent item one second less,
    so sorting locally by "favorited time" DESC matches nhentai's current favorites order.
    IDs not present in the database are skipped (no-op). Returns the number of rows actually updated.
    """
    if not ordered_ids:
        return 0
    if base_time is None:
        base_time = int(time.time())
    conn = get_conn()
    try:
        rows = [(base_time - rank, gid) for rank, gid in enumerate(ordered_ids)]
        before = conn.total_changes
        conn.executemany(
            "UPDATE doujinshi SET favorited_at = ? WHERE nhentai_id = ?", rows
        )
        conn.commit()
        return conn.total_changes - before
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_tags(tag_type=None):
    """Return the list of tags. count = how many works in my collection use this tag, not the site-wide total."""
    conn = get_conn()
    if tag_type:
        rows = conn.execute(
            """SELECT t.id, t.name, t.type,
                      COUNT(dt.doujinshi_id) as count
               FROM tags t
               INNER JOIN doujinshi_tags dt ON t.id = dt.tag_id
               WHERE t.type = ?
               GROUP BY t.id
               ORDER BY count DESC""",
            (tag_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT t.id, t.name, t.type,
                      COUNT(dt.doujinshi_id) as count
               FROM tags t
               INNER JOIN doujinshi_tags dt ON t.id = dt.tag_id
               GROUP BY t.id
               ORDER BY t.type, count DESC"""
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM doujinshi").fetchone()["cnt"]
    rated = conn.execute("SELECT COUNT(*) as cnt FROM doujinshi WHERE rating IS NOT NULL").fetchone()["cnt"]
    rating_dist = {}
    for r in [1, 2, 3]:
        c = conn.execute("SELECT COUNT(*) as cnt FROM doujinshi WHERE rating = ?", (r,)).fetchone()["cnt"]
        rating_dist[str(r)] = c
    rating_dist["unrated"] = total - rated
    artist_count = conn.execute("SELECT COUNT(*) as cnt FROM tags WHERE type = 'artist'").fetchone()["cnt"]
    conn.close()
    return {
        "total": total,
        "rated": rated,
        "rating_distribution": rating_dist,
        "artist_count": artist_count,
    }
