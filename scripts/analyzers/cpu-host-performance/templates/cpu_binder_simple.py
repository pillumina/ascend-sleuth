import argparse
import json
import logging
import os
import shutil
import subprocess
from collections import defaultdict
from typing import List, Dict, Tuple

CPU_MASK_BIT = 32
MAX_FILE_SIZE = 1024 * 1024 * 1024 * 10
LOG_MAP = {
    0: logging.DEBUG,
    1: logging.INFO,
    2: logging.WARNING,
    3: logging.ERROR
}


def execute_command(cmd: List[str]) -> Tuple[str, int]:
    with subprocess.Popen(cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
        out, err = p.communicate(timeout=1000)
        if err:
            logging.debug(f"Command stderr while running {cmd}: {err.decode()}")
    return out.decode(), p.returncode


def expand_cpu_list(cpu_str: str) -> List[int]:
    cpus = []
    try:
        for part in cpu_str.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = map(int, part.split("-"))
                cpus.extend(range(start, end + 1))
            else:
                cpus.append(int(part))
    except ValueError:
        raise RuntimeError(f"The cpu_list parameter must consist of digits, ',' and '-', which is '{cpu_str}'.")
    if not cpus:
        raise RuntimeError(f"The cpu_list parameter must consist of digits, ',' and '-', which is '{cpu_str}'.")
    return cpus


def check_path_access(path: str, writeable: bool) -> None:
    if not os.path.exists(path):
        raise RuntimeError(f"The path does not exist: {path}")
    if os.getuid() != 0 and os.stat(path).st_uid != os.getuid():
        raise RuntimeError(f"Permission mismatch: The owner of {path} does not match.")
    if os.path.islink(path):
        raise RuntimeError(f"Invalid path is a soft link: {path}")
    if writeable and not os.access(path, os.W_OK):
        raise RuntimeError(f"The path permission check failed: {path}")
    if not writeable and not os.access(path, os.R_OK):
        raise RuntimeError(f"The path permission check failed: {path}")


def read_json_file(file_path: str):
    if not os.path.isfile(file_path):
        return None
    file_size = os.path.getsize(file_path)
    if file_size <= 0:
        return None
    if file_size > MAX_FILE_SIZE:
        raise RuntimeError(f"The file size exceeds the preset value, please check the file: {file_path}")
    check_path_access(file_path, writeable=False)
    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            return json.load(json_file)
    except Exception as err:
        raise RuntimeError(f"Failed to read the file: {file_path}") from err


def build_cpu_node_map() -> Dict[int, int]:
    cpu_node: Dict[int, int] = {}
    cpu_numa_map, _ = execute_command(["lscpu", "-e=CPU,NODE"])
    for line in cpu_numa_map.splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        cpu_str, node_str = line.split()
        cpu_node[int(cpu_str)] = int(node_str)
    if not cpu_node:
        raise RuntimeError("The output of 'lscpu' is incorrect and no NUMA node is detected.")
    return cpu_node


class CustomBind:
    def __init__(self, cpu_list: List[str] = None, bind_sub_process: bool = False,
                 mem_bind: bool = False, pid: List[int] = None, irq_id: List[int] = None):
        self.bind_sub_process = bind_sub_process
        self.mem_bind = mem_bind
        self.pid = [int(value) for value in (pid or [])]
        self.irq_id = [int(value) for value in (irq_id or [])]
        self.is_irq = bool(self.irq_id)
        self.cpu_list = [expand_cpu_list(seg) for seg in (cpu_list or [])]

    @staticmethod
    def cpu_to_mask(cpus: List[int]) -> str:
        groups = defaultdict(int)
        for cpu in cpus:
            group = cpu // CPU_MASK_BIT
            bit = cpu % CPU_MASK_BIT
            groups[group] |= (1 << bit)

        max_group = max(groups.keys())
        mask_parts = []
        for group in reversed(range(max_group + 1)):
            mask_parts.append(f"{groups.get(group, 0):08x}")
        return ",".join(mask_parts)

    def select_cpu_ranges(self, target_count: int, target_name: str) -> List[List[int]]:
        if target_count <= 0:
            raise RuntimeError(f"No {target_name} is specified.")
        if not self.cpu_list:
            raise RuntimeError(f"cpu_list is required to bind {target_name}.")
        if len(self.cpu_list) == 1:
            return [self.cpu_list[0]] * target_count
        if len(self.cpu_list) != target_count:
            raise RuntimeError(
                f"The number of {target_name} ({target_count}) does not match the number of cpu_list "
                f"({len(self.cpu_list)}). Provide one cpu_list for all targets, or one cpu_list per target."
            )
        return self.cpu_list

    def irq_bind(self) -> None:
        cpu_ranges = self.select_cpu_ranges(len(self.irq_id), "irq_id")
        if not shutil.which("systemctl"):
            logging.warning("The systemctl command cannot be used in the current environment.If the irqbalance "
                            "service is enabled, manually disable the irqbalance service.Otherwise, the "
                            "interrupt-core binding cannot take effect.")
        else:
            out, return_code = execute_command(["systemctl", "list-unit-files"])
            if return_code == 0 and "irqbalance.service" in out:
                _, return_code = execute_command(["systemctl", "is-active", "--quiet", "irqbalance"])
                if return_code == 0:
                    logging.info("The irqbalance service is running and has been stopped.")
                    _, return_code = execute_command(["systemctl", "stop", "irqbalance"])
                    if return_code != 0:
                        logging.warning("The irqbalance service cannot be stopped.You need to manually stop it."
                                        "Otherwise, the interrupt-core binding cannot take effect.")

        for irq_id, cpus in zip(self.irq_id, cpu_ranges):
            affinity_file_path = f"/proc/irq/{irq_id}/smp_affinity"
            check_path_access(affinity_file_path, writeable=True)
            cpu_list_str = ",".join(map(str, cpus))
            with open(affinity_file_path, "w") as f:
                f.write(self.cpu_to_mask(cpus))
                logging.info(f"Bind the interrupt of IRQ-{irq_id} to CPU{cpu_list_str}")

    @staticmethod
    def single_numa_node(cpus: List[int], cpu_node: Dict[int, int], pid: int):
        missing = [cpu for cpu in cpus if cpu not in cpu_node]
        if missing:
            logging.warning(f"Cannot find the NUMA node of CPU{missing}, skip memory migration for pid {pid}.")
            return None
        nodes = {cpu_node[cpu] for cpu in cpus}
        if len(nodes) != 1:
            node_list = ",".join(map(str, sorted(nodes)))
            cpu_list_str = ",".join(map(str, cpus))
            logging.warning(f"CPU{cpu_list_str} for pid {pid} span NUMA nodes {node_list}. "
                            f"Skip memory migration.")
            return None
        return nodes.pop()

    def execute_bind(self, pid: int, cpus: List[int], source_numa: str, cpu_node: Dict[int, int]) -> None:
        cpu_list_str = ",".join(map(str, cpus))
        cmd = ["taskset", "-acp" if self.bind_sub_process else "-cp", cpu_list_str, str(pid)]
        logging.info(f"Bind the target (pid={pid}) to CPU{cpu_list_str}")
        _, return_code = execute_command(cmd)
        if return_code != 0:
            raise RuntimeError(f"Failed to execute the command: {' '.join(cmd)}")
        if not self.mem_bind or not shutil.which("numactl"):
            return
        target_numa = self.single_numa_node(cpus, cpu_node, pid)
        if target_numa is None:
            return
        cmd = ["migratepages", str(pid), source_numa, str(target_numa)]
        _, return_code = execute_command(cmd)
        if return_code != 0:
            logging.warning(f"Failed to execute the command: {' '.join(cmd)}")

    def bind(self, source_numa: str, cpu_node: Dict[int, int]) -> None:
        cpu_ranges = self.select_cpu_ranges(len(self.pid), "pid")
        for pid, cpus in zip(self.pid, cpu_ranges):
            self.execute_bind(pid, cpus, source_numa, cpu_node)


def load_custom_bind(data: Dict) -> List[CustomBind]:
    if not isinstance(data, dict):
        raise RuntimeError("The configuration file must be a json object.")
    items = data.get("custom_bind", [])
    if not isinstance(items, list):
        raise RuntimeError("custom_bind must be a list.")

    binders = []
    for item in items:
        if not isinstance(item, dict):
            logging.error("Skip an invalid bind entry. Each custom_bind item must be an object.")
            continue
        pid = item.get("pid") or []
        irq_id = item.get("irq_id") or []
        cpu_list = item.get("cpu_list")
        if item.get("process_name") and not pid and not irq_id:
            logging.error("process_name is not supported. Specify pid+cpu_list or irq_id+cpu_list.")
            continue
        if item.get("process_name"):
            logging.warning("process_name is ignored. Binding follows pid or irq_id in the json.")
        if bool(pid) == bool(irq_id):
            logging.error("Each bind entry must specify exactly one of 'pid' or 'irq_id' together with 'cpu_list'.")
            continue
        if not cpu_list:
            logging.error("cpu_list is required for each bind entry.")
            continue
        try:
            binders.append(CustomBind(
                cpu_list=cpu_list,
                bind_sub_process=item.get("bind_sub_process", False),
                mem_bind=item.get("mem_bind", False),
                pid=pid,
                irq_id=irq_id
            ))
        except (RuntimeError, TypeError, ValueError) as e:
            logging.error(f"Skip an invalid bind entry: {e}")
    return binders


def run(args: argparse.Namespace) -> None:
    if not args.config:
        logging.error("No configuration file is specified. Provide a json file with -c/--config. "
                      "Each entry must contain pid+cpu_list or irq_id+cpu_list.")
        return
    if not os.path.exists(args.config):
        logging.error(f"The {args.config} file does not exist.Please check and try again.")
        return
    input_data = read_json_file(args.config)
    if not input_data:
        logging.error(f"The {args.config} file is empty or invalid.")
        return
    binder_list = load_custom_bind(input_data)
    if not binder_list:
        logging.error("No valid bind entry is found in the configuration file.")
        return

    cpu_node: Dict[int, int] = {}
    source_numa = ""
    if any(bind.mem_bind and bind.pid for bind in binder_list):
        cpu_node = build_cpu_node_map()
        source_numa = ",".join(map(str, sorted(set(cpu_node.values()))))

    for loop_count, bind in enumerate(binder_list, start=1):
        logging.info(f"Start binding core round {loop_count}: {bind.__dict__}")
        try:
            if bind.is_irq:
                bind.irq_bind()
            else:
                bind.bind(source_numa, cpu_node)
        except RuntimeError as e:
            logging.error(f"Error occurred while binding: {e}")
        logging.info(f"===== Round {loop_count} of core binding has ended =====")


def main() -> None:
    parser = argparse.ArgumentParser(description="按 json 中的 pid+cpu_list 或 irq_id+cpu_list 绑核")
    parser.add_argument("-c", "--config", type=str, required=True,
                        help="绑核 json 配置文件路径")
    parser.add_argument("-l", "--log-level", type=int, default=1, choices=[0, 1, 2, 3],
                        help="日志级别，0=DEBUG，1=INFO，2=WARNING，3=ERROR")
    args = parser.parse_args()
    logging.basicConfig(level=LOG_MAP.get(args.log_level, logging.INFO),
                        format="[%(asctime)s] [%(levelname)s]:%(message)s")
    run(args)


if __name__ == "__main__":
    main()
