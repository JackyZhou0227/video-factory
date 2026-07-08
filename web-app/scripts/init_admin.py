from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import auth_store


def generate_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the initial local admin account when users table is empty.")
    parser.add_argument("--username", default="admin", help="Initial admin username. Default: admin")
    parser.add_argument("--password", default="", help="Initial admin password. Randomly generated when omitted.")
    parser.add_argument("--display-name", default="管理员", help="Initial admin display name.")
    args = parser.parse_args()

    password = args.password or generate_password()

    try:
        user, created = auth_store.create_initial_admin(
            username=args.username,
            password=password,
            display_name=args.display_name,
        )
    except ValueError as exc:
        print(f"初始化管理员失败：{exc}", file=sys.stderr)
        return 1

    if not created:
        print(f"用户表已有账号，未创建初始管理员。首个账号：{user['username']}，角色：{user['role']}")
        return 0

    print("初始管理员已创建：")
    print(f"用户名：{user['username']}")
    print(f"显示名：{user['display_name']}")
    print(f"密码：{password}")
    print("请首次登录后妥善保存或重置该密码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
