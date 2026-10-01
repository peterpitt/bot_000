"""命令列：python -m consultancy {org|demo|ask "問題"}"""
from __future__ import annotations

import argparse

from .advisors import DEPARTMENTS, org_chart
from .council import Council, TOPICS
from .demo import run_demo


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="consultancy", description="宇宙行星顧問團隊公司")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("org", help="顯示組織架構")
    sub.add_parser("demo", help="跑一次接案→派工→金流示範")
    ask = sub.add_parser("ask", help="召集智囊團回答問題（設定 XAI_API_KEY 才會呼叫 Grok）")
    ask.add_argument("question")
    ask.add_argument("--with-demo-books", action="store_true", help="附上示範公司的財務狀態")
    ask.add_argument("--show-prompt", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "org":
        print("董事會／最終決策者：使用者本人（核准所有付款與不可逆決策）")
        print("策略總召：主持激辯、收斂結論\n")
        for dept, members in org_chart().items():
            print(f"【{DEPARTMENTS[dept]}】")
            for a in members:
                print(f"  {a.emoji} {a.name} — {a.company_role}")
    elif args.cmd == "demo":
        run_demo()
    else:
        firm = None
        if args.with_demo_books:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                firm = run_demo()
        result = Council(firm).consult(args.question)
        print("分流：" + "、".join(TOPICS[t] for t in result.topics))
        print("召集：" + "、".join(f"{a.emoji}{a.name}" for a in result.advisors) + "\n")
        if args.show_prompt:
            print(result.messages[0]["content"] + "\n" + "=" * 60)
        print(result.answer)


if __name__ == "__main__":
    main()
