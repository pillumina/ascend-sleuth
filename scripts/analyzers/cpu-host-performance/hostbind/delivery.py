"""Export the supplied Linux executor verbatim and its site-specific configuration."""
import json
from pathlib import Path


SCRIPT_NAME = 'cpu_binder_simple.py'
DESIGN_NAME = 'bind_design.json'
RUN_COMMAND = 'python3 %s -c %s' % (SCRIPT_NAME, DESIGN_NAME)
TEMPLATE = Path(__file__).resolve().parents[1] / 'templates' / SCRIPT_NAME


def task_entry(task_id, cpu_range, all_threads):
    return dict(pid=[task_id], cpu_list=[cpu_range],
                bind_sub_process=all_threads, mem_bind=False)


def design_text(design):
    return json.dumps(design, ensure_ascii=False, indent=2) + '\n'


def write_delivery(directory, design):
    directory = Path(directory)
    (directory / SCRIPT_NAME).write_bytes(TEMPLATE.read_bytes())
    (directory / DESIGN_NAME).write_bytes(design_text(design).encode('utf-8'))
