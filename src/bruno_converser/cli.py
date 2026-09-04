"""Interactive command-line interface for multi-persona RAGFlow chat session."""

import sys

from bruno_converser.report_generator import generate_conversation_report
from bruno_converser.runner import ConverserRunner
from bruno_converser.session import ConversationSession, clean_persona_name
from bruno_populator.exceptions import BrunoPopulatorError
from bruno_populator.logger import get_logger

logger = get_logger("bruno_converser.cli")


def print_banner() -> None:
    """Print welcome header and command instructions."""
    print("\n========================================================")
    print("        RAGFlow Multi-Persona Converser CLI             ")
    print("========================================================")
    print("Quick Addressing & Switching:")
    print("  <index> <message>    : e.g. '2 Hello' switches to persona [2] and sends message")
    print("  <index>              : e.g. '2' switches active target to persona [2]")
    print("\nCommands:")
    print("  /personas, /list     : List available personas with indices [1, 2, ...]")
    print("  /switch <idx/name>   : Switch active persona target")
    print("  /<index>             : e.g. '/1', '/2' to switch persona directly")
    print("  /history             : Display full conversation transcript")
    print("  /report [filename]   : Export conversation report with quoted RAG references")
    print("  /clear               : Reset conversation history")
    print("  /help                : Show this help message")
    print("  /exit or /quit       : Exit converser")
    print("========================================================\n")


def display_personas(session: ConversationSession) -> None:
    """Display available personas with 1-based index numbers and highlight active target."""
    print("\nAvailable Personas:")
    index_map = session.get_persona_index_map()
    for idx, key in index_map.items():
        clean_name = clean_persona_name(key)
        prefix = "-> [ACTIVE]" if key == session.active_persona_key else "  "
        print(f"  {prefix} [{idx}] {clean_name} ({key})")
    print("")


def display_history(session: ConversationSession) -> None:
    """Display full conversation transcript."""
    if not session.history:
        print("\n[Transcript is currently empty]\n")
        return

    print("\n---------------- Conversation Transcript ----------------")
    for msg in session.history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            print(f"[User]: {content}")
        else:
            persona = clean_persona_name(msg.get("persona", "assistant"))
            print(f"[Persona: {persona}]: {content}")
    print("--------------------------------------------------------\n")


def handle_slash_command(
    user_input: str,
    session: ConversationSession,
    runner: ConverserRunner | None = None,
) -> bool:
    """
    Process slash commands.

    Returns True if a command was handled or blocked, False if not a slash input.
    Guards strictly against typos (e.g. '/siwtch'): blocks AI execution and prints help.
    """
    if not user_input.startswith("/"):
        return False

    cmd_lower = user_input.lower().strip()

    if cmd_lower in ["/exit", "/quit"]:
        print("Exiting converser session. Goodbye!")
        sys.exit(0)
    elif cmd_lower in ["/help", "/h", "/?"]:
        print_banner()
        return True
    elif cmd_lower in ["/personas", "/list", "/ls"]:
        display_personas(session)
        return True
    elif cmd_lower in ["/history", "/transcript"]:
        display_history(session)
        return True
    elif cmd_lower in ["/clear", "/reset"]:
        session.clear_history()
        print("[Conversation history cleared.]\n")
        return True
    elif cmd_lower in ["/report"] or cmd_lower.startswith("/report "):
        parts = user_input.split(maxsplit=1)
        filename = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "conversation_report.md"
        try:
            print("\nGenerating conversation report with quoted RAG references...")
            out_path = generate_conversation_report(session, runner=runner, filename=filename)
            print(f"[Success] Conversation report saved to '{out_path}'.\n")
        except Exception as exc:
            logger.error(f"Failed generating conversation report: {exc}", exc_info=True)
            print(f"[Error] Failed to generate report: {exc}\n")
        return True
    elif cmd_lower.startswith("/switch ") or cmd_lower.startswith("/talk "):
        parts = user_input.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            print("[Error] Please specify a persona index or name. Usage: /switch <index/name>")
            return True
        target = parts[1].strip()
        try:
            new_key = session.set_active_persona(target)
            new_clean = clean_persona_name(new_key)
            print(f"[Switched active persona to '{new_clean}']\n")
        except BrunoPopulatorError as exc:
            print(f"[Error] {exc}\n")
        return True

    # Check for direct numeric slash command shortcut (e.g. '/1', '/2')
    if cmd_lower[1:].isdigit():
        idx_str = cmd_lower[1:]
        try:
            new_key = session.set_active_persona(idx_str)
            new_clean = clean_persona_name(new_key)
            print(f"[Switched active persona to '[{idx_str}] {new_clean}']\n")
        except BrunoPopulatorError as exc:
            print(f"[Error] {exc}\n")
        return True

    # Unrecognized slash command (e.g. '/siwtch') -> Block execution and display help!
    print(f"\n[Error] Unrecognized command '{user_input}'. Please check for typos.")
    print_banner()
    return True


def run_cli_chat(
    session: ConversationSession | None = None,
    runner: ConverserRunner | None = None,
) -> None:
    """Start interactive command-line chat session."""
    if session is None:
        try:
            session = ConversationSession()
        except Exception as exc:
            logger.error(f"Failed to initialize ConversationSession: {exc}")
            print(f"\n[Error] Could not initialize conversation session: {exc}")
            sys.exit(1)

    if runner is None:
        try:
            runner = ConverserRunner()
        except Exception as exc:
            logger.error(f"Failed to initialize ConverserRunner: {exc}")
            print(f"\n[Error] Could not initialize converser runner: {exc}")
            sys.exit(1)

    print_banner()
    display_personas(session)

    while True:
        try:
            active_clean = clean_persona_name(session.active_persona_key)
            prompt_str = f"[User -> Persona: {active_clean}]> "
            user_input = input(prompt_str).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting converser session. Goodbye!")
            break

        if not user_input:
            continue

        # 1. Guard against slash commands & typos
        if handle_slash_command(user_input, session, runner=runner):
            continue

        # 2. Check for fast index prefixing (e.g. '2 Hallo' or '2')
        target_idx_or_name, msg_text = session.parse_prefixed_input(user_input)
        if target_idx_or_name is not None:
            try:
                new_key = session.set_active_persona(target_idx_or_name)
                new_clean = clean_persona_name(new_key)
                if not msg_text:
                    print(f"[Switched active persona to '{new_clean}']\n")
                    continue
                user_input = msg_text
                active_clean = new_clean
            except BrunoPopulatorError as exc:
                print(f"[Error] {exc}\n")
                continue

        # 3. Send message to active persona
        try:
            print(f"Sending message to Persona '{active_clean}'...")
            answer = runner.send_message(session, user_input)
            print(f"\n[Persona: {active_clean}]\n{answer}\n")
        except Exception as exc:
            logger.error(f"Chat execution failed: {exc}", exc_info=True)
            print(f"\n[Error] Failed to get response from persona: {exc}\n")
