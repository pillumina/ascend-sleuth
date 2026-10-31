#!/bin/bash
# ==========================================================
# CPU Host 性能采集脚本 (cpu_trace_collect.sh) — 统一采集入口
# - 仅依赖 bash + ftrace(tracefs/debugfs) + /proc + /sys，无第三方软件
# - 采集前后保存/恢复 tracing 原配置，不破坏客户现场
# - 支持: --duration / --output / --buffer-size / --cpu-list / --minimal / --pid
# - --pid <PID[,PID...]>: 追加 HostBound 只读快照 (NUMA/NPU 拓扑、IRQ、目标进程
#   及线程 affinity 等), 写入采集包 hostbound/ 目录; 不改变 ftrace 事件与恢复行为
# - 全程进度展示: 阶段导航 + 动态进度条 (百分比/已用时/预计剩余/速率/事件数),
#   管道或重定向输出时自动降级为纯文本日志 (无 ANSI 颜色与 \r 刷新, 支持 NO_COLOR)
# - 产物: cpu_trace_YYYYMMDD_HHMMSS.tar.gz (trace + 系统快照, 加 --pid 时含 hostbound/)
# ==========================================================
set +e  # 单项能力缺失不致命，由脚本自行控制

# ==========================================================
# 进度展示组件 (自包含; 非终端输出时自动降级为纯文本日志)
# ==========================================================
IS_TTY=0; [[ -t 1 ]] && IS_TTY=1   # 进度条/颜色仅输出到终端, 管道下保持日志干净
if [[ $IS_TTY -eq 1 && -z "$NO_COLOR" ]]; then
  C_RST=$'\033[0m'; C_DIM=$'\033[2m'; C_B=$'\033[1m'
  C_R=$'\033[31m'; C_G=$'\033[32m'; C_Y=$'\033[33m'
  C_C=$'\033[36m'; C_BL=$'\033[34m'
else
  C_RST=""; C_DIM=""; C_B=""; C_R=""; C_G=""; C_Y=""; C_C=""; C_BL=""
fi
info(){  echo -e "$C_C[Info]$C_RST $*"; }
ok(){    echo -e "$C_G[OK]  $C_RST$*"; }
warn(){  echo -e "$C_Y[Warn]$C_RST $*"; }
err(){   echo -e "$C_B$C_R[Err] $C_RST$*"; }

# ---------- 数值/时间格式化 ----------
fmt_bytes(){ awk -v b="${1:-0}" 'BEGIN{split("B KB MB GB TB PB",u," ");i=1;while(b>=1024&&i<6){b/=1024;i++}printf "%.1f%s",b,u[i]}'; }
fmt_num(){   awk -v n="${1:-0}" 'BEGIN{if(n>=1e9)printf "%.2fG",n/1e9;else if(n>=1e6)printf "%.2fM",n/1e6;else if(n>=1e3)printf "%.1fK",n/1e3;else printf "%d",n}'; }
fmt_secs(){  local s=${1:-0}
  if   (( s>=3600 )); then printf "%dh%02dm%02ds" $((s/3600)) $((s%3600/60)) $((s%60))
  elif (( s>=60   )); then printf "%dm%02ds"      $((s/60))     $((s%60))
  else printf "%ds" "$s"; fi; }

# ---------- 刷新节奏 (不支持小数 sleep 的环境自动退化为 1s) ----------
SLEEP_FRAC=1; sleep 0.1 2>/dev/null || SLEEP_FRAC=0
SPIN_STEP=0.1;  (( SLEEP_FRAC )) || SPIN_STEP=1
POLL_STEP=0.3;  (( SLEEP_FRAC )) || POLL_STEP=1

# ---------- 阶段导航 ----------
PHASE_CUR=0; PHASE_TOTAL=4; PHASE_T0=0
phase_begin(){
  PHASE_CUR=$((PHASE_CUR+1)); PHASE_T0=$SECONDS; LAST_BUCKET=-1
  echo -e "\n${C_BL}${C_B}[$PHASE_CUR/$PHASE_TOTAL]${C_RST} ${C_C}▶${C_RST} ${C_B}$1${C_RST}"
}
phase_end(){
  echo -e "  ${C_G}✓${C_RST} $* ${C_DIM}· 用时 $(fmt_secs $((SECONDS-PHASE_T0)))${C_RST}"
}

# ---------- 平滑进度条 (█▉▊▋▌▍▎▏ 八级字符块) ----------
BAR_W=24; LAST_BUCKET=-1
bar(){
  local pct=$1; (( pct<0 )) && pct=0; (( pct>100 )) && pct=100
  local units=$(( pct*BAR_W*8/100 ))   # 注意: 同一 local 语句中后项引用不到前项, 须分行
  local full=$(( units/8 )) rem=$(( units%8 ))
  local filled="" blank="" i
  local seg=( "" ▏ ▎ ▍ ▌ ▋ ▊ ▉ )
  for ((i=0;i<full;i++)); do filled+="█"; done
  local rest=$(( BAR_W - full - (rem>0 ? 1 : 0) ))
  for ((i=0;i<rest;i++)); do blank+="░"; done
  local col=$C_C; (( pct>=100 )) && col=$C_G
  printf "%s%s%s%s%s" "$col$C_B" "$filled${seg[rem]}" "$C_RST$C_DIM" "$blank" "$C_RST"
}
progress_update(){   # 用法: progress_update <标签> <0-100> <附加信息>
  local label=$1 pct=$2 extra=$3
  if [[ $IS_TTY -eq 1 ]]; then
    printf "\r  %s %s %s%3d%%%s %s\033[K" "$C_B$label$C_RST" "$(bar "$pct")" "$C_B" "$pct" "$C_RST" "$extra"
  else
    local bucket=$(( pct/10 ))   # 非 TTY: 每跨过 10% 打一行纯文本日志
    (( bucket>LAST_BUCKET )) && { LAST_BUCKET=$bucket; info "$label 进度 ${pct}% $extra"; }
  fi
}
progress_clear(){ [[ $IS_TTY -eq 1 ]] && printf "\r\033[K"; return 0; }

# ---------- 旋转指示器 (用于无法计算百分比的步骤, 如 tar 打包) ----------
SPIN_PID=""
spin_start(){   # 用法: spin_start "提示"
  [[ $IS_TTY -eq 1 ]] || return 0
  local msg=$1 frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏) i=0 t0=$SECONDS
  ( while :; do
      printf "\r  %s%s%s %s %s已用时 %s%s\033[K" \
        "$C_C$C_B" "${frames[i]}" "$C_RST" "$msg" "$C_DIM" "$(fmt_secs $((SECONDS-t0)))" "$C_RST"
      i=$(( (i+1)%${#frames[@]} )); sleep "$SPIN_STEP"
    done ) & SPIN_PID=$!
}
spin_stop(){
  [[ -n "$SPIN_PID" ]] || return 0
  kill "$SPIN_PID" 2>/dev/null; wait "$SPIN_PID" 2>/dev/null
  SPIN_PID=""; progress_clear
}

# ---------- ftrace 实时统计 (采集进度条展示用; 读取零开销, 不污染 trace) ----------
trace_stats(){   # 汇总各 CPU buffer 统计, 输出: "已驻留事件 丢弃事件 溢出次数"
  # 先显式展开文件列表: mawk 在文件缺失时不执行 END 块, 不能依赖其回退
  local f files=()
  for f in "$TRACE_DIR"/per_cpu/cpu*/stats; do [[ -f "$f" ]] && files+=("$f"); done
  if ((${#files[@]})); then
    awk -F': *' '
      $1 ~ /^(entries|unread)/          {e+=$2}
      $1 ~ /^dropped/                   {d+=$2}
      $1 ~ /^overrun/ && $1 !~ /commit/ {o+=$2}
      END { printf "%d %d %d", e+0, d+0, o+0 }' "${files[@]}" 2>/dev/null
  else
    echo "0 0 0"
  fi
}

# ---------- 顶部横幅 ----------
print_banner(){
  local mode="全量"; [[ $MINIMAL -eq 1 ]] && mode="精简"
  local cpus="全部 ($(nproc 2>/dev/null || echo '?') 核)"; [[ -n "$CPU_LIST" ]] && cpus="$CPU_LIST"
  local hb="无"; [[ -n "$PID_LIST" ]] && hb="$PID_LIST"
  local evs; evs=$(echo $ENABLED_EVENTS | wc -w); evs=${evs//[!0-9]/}
  echo -e "$C_C"
  echo  "┌──────────────────────────────────────────────────────────────"
  echo -e "│ ${C_B}CPU Host 性能采集${C_RST}${C_C}  cpu_trace_collect.sh"
  echo  "│  模式: $mode   CPU: $cpus   时长: ${DURATION}s   Buffer: ${BUFFER_SIZE}KB/核"
  echo  "│  事件: ${evs:-?} 个   HostBound: $hb   输出: $(realpath "$OUTDIR" 2>/dev/null || echo "$OUTDIR")"
  echo  "└──────────────────────────────────────────────────────────────"
  echo -e "$C_RST"
}

usage() {
cat <<EOF
CPU Host 性能采集工具 (统一入口: 全量 ftrace + 可选 HostBound 快照)
用法: sudo bash $0 [选项]
  -t, --duration <秒>     采集时长, 默认 30
  -o, --output <目录>     输出目录, 默认当前目录
  -b, --buffer-size <KB>  单核 buffer 大小, 默认 140800
  -c, --cpu-list <列表>   CPU 列表, 如 1,2,3 或 0-47 (默认全量)
  -m, --minimal           精简模式: 仅采集 sched_switch, 体积减小 90%+
  -p, --pid <PID[,PID]>   追加 HostBound 只读快照: NUMA/NPU 拓扑、IRQ、目标进程与
                          线程 affinity 等, 写入 hostbound/ 目录 (不改 ftrace 采集)
  -h, --help              显示帮助
示例:
  sudo bash $0 --duration 30
  sudo bash $0 -t 10 -m
  sudo bash $0 -t 60 -c 0-47 -b 281600
  sudo bash $0 --duration 30 --pid 12345
  sudo bash $0 --duration 30 --pid 12345,6789
EOF
}

# ---------- 参数解析 ----------
DURATION=30; OUTDIR="."; BUFFER_SIZE=140800; CPU_LIST=""; MINIMAL=0; PID_LIST=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--duration)    DURATION="$2"; shift 2;;
    -o|--output)      OUTDIR="$2"; shift 2;;
    -b|--buffer-size) BUFFER_SIZE="$2"; shift 2;;
    -c|--cpu-list)    CPU_LIST="$2"; shift 2;;
    -m|--minimal)     MINIMAL=1; shift;;
    -p|--pid)         PID_LIST="$2"; shift 2;;
    -h|--help)        usage; exit 0;;
    *) err "未知参数: $1"; usage; exit 1;;
  esac
done
if [[ "$DURATION" =~ ^[0-9]+$ ]] && [[ "$BUFFER_SIZE" =~ ^[0-9]+$ ]] && (( DURATION>=1 )); then :; else
  err "时长必须为 ≥1 的纯数字, buffer 必须为纯数字"; exit 1; fi
# PID 合法性: 逗号分隔的正整数 (不校验进程是否存在, 采集阶段自动跳过)
for _p in ${PID_LIST//,/ }; do
  [[ "$_p" =~ ^[1-9][0-9]*$ ]] || { err "pid 必须为正整数: $_p"; exit 1; }
done
if [[ "$EUID" -ne 0 ]]; then
  err "请使用 root 权限运行: sudo bash $0"; exit 1; fi
# 阶段总数: 快照/采集/导出/打包 (+ 可选 HostBound 快照)
PHASE_TOTAL=4; [[ -n "$PID_LIST" ]] && PHASE_TOTAL=5

# ---------- 定位 tracefs ----------
TRACE_DIR=""
for d in /sys/kernel/tracing /sys/kernel/debug/tracing; do
  [[ -d "$d" ]] && TRACE_DIR="$d" && break
done
if [[ -z "$TRACE_DIR" ]]; then
  err "未找到 tracefs/debugfs (需内核开启 CONFIG_FTRACE 并挂载 debugfs)"; exit 1; fi
ok "使用 tracing 目录: $TRACE_DIR"
# per_cpu stats 可读时, 采集进度条额外展示已捕获事件数/速率/丢弃告警
STATS_OK=0; compgen -G "$TRACE_DIR/per_cpu/cpu*/stats" >/dev/null 2>&1 && STATS_OK=1
if ! echo test_probe_write >/dev/null 2>&1 && [[ ! -w "$TRACE_DIR/tracing_on" ]]; then
  err "tracing 目录不可写, 请确认 root 权限"; exit 1; fi

# ---------- CPU 掩码 ----------
to_mask() {  # "0-3,8" -> 16 进制 mask (每 32 核一组逗号分隔)
  echo "$1" | awk '{ gsub(/\[|\]|[[:space:]]/,""); n=split($0,p,",");
    delete cores; maxc=-1
    for(i=1;i<=n;i++){ if(p[i]~/-/){split(p[i],r,"-");for(c=r[1];c<=r[2];c++){cores[c]=1;if(c>maxc)maxc=c}}
      else if(p[i]~/^[0-9]+$/){cores[p[i]]=1;if(p[i]+0>maxc)maxc=p[i]+0} }
    if(maxc<0){print "";} else {
      nh=int((maxc+32)/32); nh*=32; mask=""
      for(c=0;c<nh;c++){bit=0; if(cores[c])bit=1; g=int(c/32); hex[g]+=bit*2^(c%32)}
      for(g=nh/32-1;g>=0;g--){s=sprintf("%08x",hex[g]); mask=(mask=="")?s:mask","s}
      print mask } }'
}
SAVED_MASK=$(cat "$TRACE_DIR/tracing_cpumask" 2>/dev/null)
if [[ -n "$CPU_LIST" ]]; then
  CPU_MASK=$(to_mask "$CPU_LIST")
  [[ -z "$CPU_MASK" ]] && { err "CPU 列表解析失败: $CPU_LIST"; exit 1; }
  echo "$CPU_MASK" > "$TRACE_DIR/tracing_cpumask" || { err "写入 tracing_cpumask 失败"; exit 1; }
fi

# ---------- 事件集合 ----------
if [[ "$MINIMAL" -eq 1 ]]; then
  EVENT_LIST="sched/sched_switch"
else
  EVENT_LIST="sched/sched_migrate_task sched/sched_wakeup sched/sched_waking sched/sched_switch \
sched/sched_wakeup_new task/task_newtask irq/irq_handler_entry irq/irq_handler_exit \
irq/softirq_entry irq/softirq_exit irq/softirq_raise power/cpu_idle power/cpu_frequency"
fi

# ---------- 保存原配置 (结束后恢复) ----------
SAVED_ON=$(cat "$TRACE_DIR/tracing_on" 2>/dev/null)
SAVED_EVENTS=$(cat "$TRACE_DIR/events/enable" 2>/dev/null)
SAVED_TRACER=$(cat "$TRACE_DIR/current_tracer" 2>/dev/null)
SAVED_BUF=$(cat "$TRACE_DIR/buffer_size_kb" 2>/dev/null)
cleanup() {
  info "恢复 tracing 原始配置..."
  echo "$SAVED_ON"     > "$TRACE_DIR/tracing_on"     2>/dev/null
  echo "$SAVED_TRACER" > "$TRACE_DIR/current_tracer" 2>/dev/null
  echo "$SAVED_BUF"    > "$TRACE_DIR/buffer_size_kb" 2>/dev/null
  [[ -n "$SAVED_MASK" ]] && echo "$SAVED_MASK" > "$TRACE_DIR/tracing_cpumask" 2>/dev/null
  # 关闭本次启用的事件后, 恢复全局 enable 原值
  for ev in $ENABLED_EVENTS; do echo 0 > "$TRACE_DIR/events/$ev/enable" 2>/dev/null; done
  echo "$SAVED_EVENTS" > "$TRACE_DIR/events/enable" 2>/dev/null
  echo > "$TRACE_DIR/trace" 2>/dev/null
}
abort(){
  progress_clear
  for j in $(jobs -pr 2>/dev/null); do kill "$j" 2>/dev/null; done  # 停掉后台导出/指示器
  err "检测到中断信号, 停止采集并恢复环境..."
  [[ -n "${SNAP:-}" ]] && rm -f "$SNAP"/.part_*.txt 2>/dev/null
  cleanup
  exit 1
}
trap abort INT TERM
ENABLED_EVENTS=""

# ---------- 环境初始化 ----------
echo 0 > "$TRACE_DIR/tracing_on" 2>/dev/null
echo nop > "$TRACE_DIR/current_tracer" 2>/dev/null
echo "$BUFFER_SIZE" > "$TRACE_DIR/buffer_size_kb" 2>/dev/null \
  && ok "buffer_size_kb = $BUFFER_SIZE" || warn "设置 buffer 失败, 使用默认值"
echo > "$TRACE_DIR/trace" 2>/dev/null

for ev in $EVENT_LIST; do
  if [[ -f "$TRACE_DIR/events/$ev/enable" ]]; then
    echo 1 > "$TRACE_DIR/events/$ev/enable" && ENABLED_EVENTS="$ENABLED_EVENTS $ev"
  else
    warn "内核不支持事件: $ev (跳过)"
  fi
done
[[ -z "$ENABLED_EVENTS" ]] && { err "没有任何可用事件, 无法采集"; cleanup; exit 1; }
ok "已启用事件:$ENABLED_EVENTS"
print_banner

# ---------- 系统快照 ----------
mkdir -p "$OUTDIR/cpu_trace" || { err "创建输出目录失败: $OUTDIR"; exit 1; }
SNAP="$OUTDIR/cpu_trace"
snap_file(){ [[ -r "$1" ]] && cp "$1" "$SNAP/$2" 2>/dev/null || echo "N/A (文件不存在)" > "$SNAP/$2"; }
phase_begin "采集系统静态快照 (/proc, /sys)"
snap_file /proc/cpuinfo     cpuinfo.txt
snap_file /proc/stat        proc_stat.txt
snap_file /proc/loadavg     loadavg.txt
snap_file /proc/meminfo     meminfo.txt
snap_file /proc/interrupts  interrupts.txt
snap_file /proc/softirqs    softirqs.txt
snap_file /proc/schedstat   schedstat.txt
snap_file /proc/vmstat      vmstat.txt
snap_file /sys/devices/system/cpu/online  cpu_online.txt
# cpufreq 汇总 (存在则采集)
{ for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq; do
    [[ -r "$f" ]] && echo "$f: $(cat "$f" 2>/dev/null)"; done; } > "$SNAP/cpufreq.txt" 2>/dev/null
{ [[ -d /sys/devices/system/node ]] && for f in /sys/devices/system/node/node*/cpulist /sys/devices/system/node/node*/meminfo; do
    [[ -r "$f" ]] && echo "== $f =="; cat "$f" 2>/dev/null; done; } > "$SNAP/numa.txt" 2>/dev/null
# 系统信息 (命令存在才执行, 失败不致命)
{ echo "hostname: $(hostname 2>/dev/null)"; echo "date: $(date '+%Y-%m-%d %H:%M:%S')"; \
  echo "uname: $(uname -a 2>/dev/null)"; echo "nproc: $(nproc 2>/dev/null)"; \
  command -v lscpu   >/dev/null && lscpu; \
  command -v numactl >/dev/null && numactl -H; } > "$SNAP/system_info.txt" 2>/dev/null
phase_end "静态快照已写入 $SNAP/"

# ---------- 执行采集 ----------
START_TS=$(date +%s); START_TIME=$(date "+%Y-%m-%d %H:%M:%S")
echo "$START_TIME" > "$SNAP/trace_start_time.txt"
phase_begin "ftrace 采集 (${DURATION}s · $([[ $MINIMAL -eq 1 ]] && echo 精简 || echo 全量)模式$([[ -n "$PID_LIST" ]] && echo " · HostBound:$PID_LIST"))"
echo 1 > "$TRACE_DIR/tracing_on" || { err "开启 tracing 失败"; cleanup; exit 1; }
T_COL0=$SECONDS; PREV_E=0; PREV_T=$T_COL0
# 刷新节奏自适应: 短采集 0.5s 刷新, 越长越稀疏, 减少无谓开销
COLLECT_STEP=0.5
if (( DURATION>120 && DURATION<=600 )); then COLLECT_STEP=1; elif (( DURATION>600 )); then COLLECT_STEP=2; fi
(( SLEEP_FRAC )) || COLLECT_STEP=1
while :; do
  sleep "$COLLECT_STEP"
  ELAPSED=$((SECONDS-T_COL0)); (( ELAPSED>DURATION )) && ELAPSED=$DURATION
  PCT=$(( ELAPSED*100/DURATION ))
  EXTRA="│ ${C_B}$(fmt_secs "$ELAPSED")${C_RST}/$(fmt_secs "$DURATION") │ 余 $(fmt_secs $((DURATION-ELAPSED)))"
  if [[ $STATS_OK -eq 1 ]]; then
    read -r EV DROP OV <<< "$(trace_stats)"
    EV=${EV:-0}; DROP=${DROP:-0}
    DELTA=$(( EV-PREV_E )); (( DELTA<0 )) && DELTA=0
    RATE=0; (( SECONDS>PREV_T )) && RATE=$(( DELTA/(SECONDS-PREV_T) ))
    PREV_E=$EV; PREV_T=$SECONDS
    EXTRA+=" │ 已捕获 ${C_B}$(fmt_num "$EV")${C_RST} 事件 (${C_DIM}$(fmt_num "$RATE")/s${C_RST})"
    if (( DROP>0 )); then EXTRA+=" │ ${C_Y}丢弃 $DROP${C_RST}"; else EXTRA+=" │ ${C_DIM}丢弃 0${C_RST}"; fi
  fi
  progress_update "采集" "$PCT" "$EXTRA"
  (( ELAPSED>=DURATION )) && break
done
progress_clear
echo 0 > "$TRACE_DIR/tracing_on"
END_TIME=$(date "+%Y-%m-%d %H:%M:%S"); echo "$END_TIME" > "$SNAP/trace_end_time.txt"
phase_end "采集结束 ($END_TIME)"

# 提速: 慢的根源是内核读取 trace 文件时逐条 format 成文本且只能单线程进行。
# 改为并行读取各 CPU 独立缓冲区 (多核同时 format, 近 N 核倍提速), 再拼接为单文件。
# 拼接结果与全局 trace 内容一致, 仅跨 CPU 行序不同 —— 分析器会按时间戳统一排序, 不影响结果。
shopt -s nullglob
PER_CPU_TRACES=("$TRACE_DIR"/per_cpu/cpu*/trace)
if [[ ${#PER_CPU_TRACES[@]} -gt 0 ]]; then
  phase_begin "导出 trace (并行读取 ${#PER_CPU_TRACES[@]} 个 CPU 缓冲区, 并发 ≤16)"
  MAX_PAR=16; T_EXP0=$SECONDS; TOTAL=${#PER_CPU_TRACES[@]}
  declare -A RUNNING=(); NEXT=0; DONE=0; BYTES=0
  while (( DONE < TOTAL )); do
    # 有空闲并发槽位则继续派发
    if (( NEXT < TOTAL )) && (( ${#RUNNING[@]} < MAX_PAR )); then
      cat "${PER_CPU_TRACES[NEXT]}" > "$SNAP/.part_$NEXT.txt" 2>/dev/null &
      RUNNING[$!]=$NEXT; NEXT=$((NEXT+1)); continue
    fi
    sleep "$POLL_STEP"
    # 回收已完成的导出任务
    for pid in "${!RUNNING[@]}"; do
      if ! kill -0 "$pid" 2>/dev/null; then
        wait "$pid" 2>/dev/null; unset "RUNNING[$pid]"; DONE=$((DONE+1))
      fi
    done
    BYTES=$(stat -c %s "$SNAP"/.part_*.txt 2>/dev/null | awk '{s+=$1}END{print s+0}')
    ELAPSED=$((SECONDS-T_EXP0)); (( ELAPSED<1 )) && ELAPSED=1
    ETA="…"; SPD="…"
    if (( DONE>0 )); then
      ETA=$(fmt_secs $(( ELAPSED/DONE*(TOTAL-DONE) )))
      SPD="$(fmt_bytes $(( BYTES/ELAPSED )))/s"
    fi
    progress_update "导出" $(( DONE*100/TOTAL )) \
      "│ ${C_B}$DONE${C_RST}/$TOTAL 核 │ $(fmt_bytes "$BYTES") │ ${C_C}$SPD${C_RST} │ 余 $ETA"
  done
  progress_clear
  BYTES=$(stat -c %s "$SNAP"/.part_*.txt 2>/dev/null | awk '{s+=$1}END{print s+0}')
  EXP_ELAPSED=$((SECONDS-T_EXP0)); (( EXP_ELAPSED<1 )) && EXP_ELAPSED=1
  spin_start "拼接各 CPU 分片 -> trace.txt"
  cat "$SNAP"/.part_*.txt > "$SNAP/trace.txt" 2>/dev/null
  rm -f "$SNAP"/.part_*.txt
  spin_stop
  phase_end "已并行导出 $TOTAL 个 CPU 缓冲区, 共 $(fmt_bytes "$BYTES") (平均 $(fmt_bytes $(( BYTES/EXP_ELAPSED )))/s)"
else
  # per_cpu 目录不存在时回退为读取全局 trace (兼容旧内核/特殊配置)
  phase_begin "导出 trace (兼容模式: 全局缓冲区)"
  spin_start "读取全局 trace 缓冲区"
  cat "$TRACE_DIR/trace" > "$SNAP/trace.txt" 2>/dev/null
  spin_stop
  phase_end "已导出全局 trace 缓冲区 ($(fmt_bytes "$(stat -c %s "$SNAP/trace.txt" 2>/dev/null || echo 0)"))"
fi
shopt -u nullglob
[[ -s "$SNAP/trace.txt" ]] || { err "trace 为空, 事件可能未产生或 buffer 溢出"; }
# 记录 buffer 溢出情况 (注意: glob 不能加引号, 否则不展开)
cat "$TRACE_DIR"/per_cpu/cpu*/stats/overrun 2>/dev/null | paste -sd+ | bc > "$SNAP/trace_overrun.txt" 2>/dev/null

cleanup

# ---------- HostBound 只读快照 (仅 --pid 时执行) ----------
# 写入 $SNAP/hostbound/, 随采集包一并打包; 文件名布局与分析器约定一致。
snapshot_hostbound() {
  local HB="$SNAP/hostbound"
  mkdir -p "$HB" 2>/dev/null || { warn "无法创建 hostbound 快照目录, 跳过"; return 0; }
  _hbcap(){ "$@" > "$HB/$1.txt" 2>&1 || true; }
  _hbcap nproc
  _hbcap lscpu
  _hbcap numactl -H
  _hbcap taskset -pc 1
  cp /proc/interrupts "$HB/interrupts_at_end.txt" 2>/dev/null || true
  cp /proc/softirqs    "$HB/softirqs_at_end.txt" 2>/dev/null || true
  { cat /proc/cmdline; echo; } > "$HB/kernel_cmdline.txt" 2>/dev/null || true
  if command -v npu-smi >/dev/null 2>&1; then
    npu-smi info         > "$HB/npu_smi_info.txt" 2>&1 || true
    npu-smi info -m      > "$HB/npu_smi_map.txt" 2>&1 || true
    npu-smi info -t topo > "$HB/npu_smi_topology.txt" 2>&1 || true
  fi
  local p tid
  for p in ${PID_LIST//,/ }; do
    [[ -d "/proc/$p" ]] || { warn "进程不存在, 跳过其快照: $p"; continue; }
    cp "/proc/$p/status" "$HB/pid_${p}_status.txt" 2>/dev/null || true
    taskset -pc "$p" > "$HB/pid_${p}_affinity.txt" 2>&1 || true
    ps -T -p "$p" -o pid,tid,psr,pcpu,stat,comm > "$HB/pid_${p}_threads.txt" 2>&1 || true
    while read -r tid; do taskset -pc "$tid"; done < <(ls "/proc/$p/task") \
      > "$HB/pid_${p}_thread_affinity.txt" 2>&1 || true
  done
  # 清单: 记录本次未运行的外部工具, 避免把缺失数据误当作正常
  cat > "$HB/collection_manifest.json" <<EOF
{"collector":"cpu_trace_collect.sh","mode":"unified","duration_sec":$DURATION,"pid":"${PID_LIST}","minimal":$MINIMAL,"ftrace":"cpu_trace_collect.sh","external_tools":{"gil_tracer":"not_run","function_monitor":"not_run","msprof":"not_run","host_analyzer":"not_run"}}
EOF
}
if [[ -n "$PID_LIST" ]]; then
  phase_begin "HostBound 只读快照 (PID: $PID_LIST)"
  snapshot_hostbound
  phase_end "HostBound 快照已写入 hostbound/ 目录"
fi

# ---------- 元数据与打包 ----------
cat > "$SNAP/metadata.txt" <<EOF
collect_tool: cpu_trace_collect.sh
start_time: $START_TIME
end_time: $END_TIME
duration_sec: $DURATION
minimal_mode: $MINIMAL
cpu_list_input: ${CPU_LIST:-all}
hostbound_pid: ${PID_LIST:-none}
enabled_events:$ENABLED_EVENTS
kernel: $(uname -r 2>/dev/null)
hostname: $(hostname 2>/dev/null)
trace_dir: $TRACE_DIR
EOF
phase_begin "打包采集包 (tar.gz 压缩)"
PKG=$(realpath "$OUTDIR" 2>/dev/null || echo "$OUTDIR")/cpu_trace_$(date +%Y%m%d_%H%M%S).tar.gz
spin_start "压缩打包中, 数据量大时需要数分钟"
if tar -czf "$PKG" -C "$OUTDIR" cpu_trace 2>/dev/null; then
  spin_stop
  PKG_SIZE=$(stat -c %s "$PKG" 2>/dev/null || echo 0)
  phase_end "打包完成"
  echo
  echo -e "${C_G}┌──────────────────────────────────────────────────────────────"
  echo -e "│ ${C_B}✔ 采集完成!${C_RST}${C_G} 总耗时 $(fmt_secs "$SECONDS")"
  echo -e "│${C_RST} 采集包: ${C_B}$PKG${C_RST} ${C_DIM}($(fmt_bytes "$PKG_SIZE"))${C_RST}"
  echo -e "${C_DIM}│ 提示: 可直接用本 Skill 分析, 或拖入 https://ui.perfetto.dev 查看${C_RST}"
  echo -e "${C_G}└──────────────────────────────────────────────────────────────${C_RST}"
else
  spin_stop
  warn "打包失败, 原始数据保留在: $SNAP/"
  ok "请将整个 cpu_trace 目录回传用于分析"
fi
exit 0
