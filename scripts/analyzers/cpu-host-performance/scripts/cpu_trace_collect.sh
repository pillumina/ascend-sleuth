#!/bin/bash
# ==========================================================
# CPU Host 性能采集脚本 (cpu_trace_collect.sh) — 统一采集入口
# - Bash 4+ + awk + ftrace + /proc + /sys；单文件。原生 Ascend Dump 使用 Python 3
# - 仅写独立 trace instance，退出时清理，不修改全局 tracing
# - 默认 3 秒全量采集；--no-hostbound 显式降级，--minimal 仅精简 trace 事件
# - --pid <PID[,PID...]>: 追加 HostBound 只读快照 (NUMA/NPU 拓扑、IRQ、目标进程
#   及线程 affinity 等), 写入采集包 hostbound/ 目录; 不改变 ftrace 事件与恢复行为
# - 全程进度展示: 阶段导航 + 动态进度条 (百分比/已用时/预计剩余/速率/事件数),
#   管道或重定向输出时自动降级为纯文本日志 (无 ANSI 颜色与 \r 刷新, 支持 NO_COLOR)
# - 产物: cpu_trace_YYYYMMDD_HHMMSS_XXXXXX.tar.gz (trace + 系统快照 + hostbound/ 证据清单)
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
  local hb="无"; (( HOSTBOUND )) && hb="自动发现全部 NPU PID + $PID_LIST"
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
CPU Host 性能采集工具 (统一入口: 默认全量 ftrace + HostBound + 进程发现)
用法: sudo bash $0 [选项]
  -t, --duration <秒>     采集时长, 默认 3 (default: 3 s)
  -o, --output <目录>     输出目录, 默认当前目录
  -b, --buffer-size <KB>  单核 buffer 大小, 默认 16384
  -c, --cpu-list <列表>   CPU 列表, 如 1,2,3 或 0-47 (默认全量)
  -m, --minimal           精简模式: 仅 sched_switch；sysfs 频率仍低频轮询
  -p, --pid <PID[,PID]>   追加目标进程的 NUMA、affinity、启动变量白名单、已加载库与进程限额
      --hostbound        自动发现全部 NPU 占卡宿主机 PID 并采集亲和性快照
      --no-hostbound     显式关闭 NPU/目标进程/全进程发现；仍采集系统能力与频率
      --ascend-dump-script <路径>
                         覆盖默认内置的 msprechecker_dump.py
      --no-ascend-dump   跳过原生环境 JSON。默认在宿主机有 python3 时采集并随包交付
      --discover         只读 /proc 全进程/全线程前后快照与生命周期事件
      --frequency-interval <秒>  sysfs 轮询，默认1，最小0.2
      --full             显式全量模式（默认）
  -h, --help              显示帮助
示例:
  sudo bash $0 --duration 30
  sudo bash $0 -t 10 -m
  sudo bash $0 -t 60 -c 0-47 -b 281600
  sudo bash $0 --duration 30 --pid 12345
  sudo bash $0 --duration 30 --pid 12345,6789
  sudo bash $0 --duration 30 --hostbound
EOF
}

# BEGIN standalone evidence
# All normalized sidecars are produced by Bash + POSIX awk; no interpreter helper.
HB_PROC=/proc; HB_SYS=/sys
hb_quote(){ LC_ALL=C awk 'BEGIN{for(i=1;i<32;i++)esc[sprintf("%c",i)]=sprintf("\\u%04x",i)} {if(NR>1)s=s "\n";s=s $0} END{out="\"";for(i=1;i<=length(s);i++){c=substr(s,i,1);out=out (c=="\\"?"\\\\":c=="\""?"\\\"":c in esc?esc[c]:c)}print out "\""}'; }
hb_now(){ date -u +%FT%TZ; }
hb_snapshot(){
  local kind=$1 output=$2 p t paths=()
  case "$kind" in
    process) for p in "$HB_PROC"/[0-9]*; do
      [[ -d "$p" ]] || continue; paths+=("P" "$p")
      for t in "$p"/task/[0-9]*; do [[ -d "$t" ]] && paths+=("T" "$t"); done
    done;;
    frequency)
      for p in "$HB_SYS"/devices/system/cpu/cpufreq/policy[0-9]*; do [[ -d "$p" ]] && paths+=(F "$p"); done
      if ((${#paths[@]}==0)); then
        for p in "$HB_SYS"/devices/system/cpu/cpu[0-9]*/cpufreq; do [[ -d "$p" ]] && paths+=(F "$p"); done
      fi;;
    idle) for p in "$HB_SYS"/devices/system/cpu/cpu[0-9]*/cpuidle/state*; do [[ -d "$p" ]] && paths+=(I "$p"); done;;
    topology) for p in "$HB_SYS"/devices/system/node/node[0-9]*; do [[ -d "$p" ]] && paths+=(N "$p"); done;;
  esac
  # One awk process per snapshot, not one process per thread or sysfs field.
  printf '%s\n' "${paths[@]}" | LC_ALL=C awk -v kind="$kind" -v pr="$HB_PROC" -v sy="$HB_SYS" -v ticks="${HB_TICKS:-100}" -v countfile="$SNAP/hostbound/.snapshot_count" '
  function q(s, i,c,o){o="\"";for(i=1;i<=length(s);i++){c=substr(s,i,1);o=o (c=="\\"?"\\\\":c=="\""?"\\\"":c in esc?esc[c]:c)}return o "\""}
  function readfile(p, x,s,r){s="";found=0;while((r=(getline x < p))>0){s=s (found?"\n":"") x;found=1}close(p);exists=(r>=0);return s}
  function stamp( a){split(readfile(pr "/uptime"),a," ");return a[1]+0}
  function basename(p,a,n){n=split(p,a,"/");return a[n]}
  function cpus(s, a,b,n,i,j,o,sep){gsub(/,/," ",s);n=split(s,a,/[[:space:]]+/);o="[";sep="";for(i=1;i<=n;i++){if(a[i]=="")continue;split(a[i],b,"-");if(b[1]!~/^[0-9]+$/ || (b[2]!="" && (b[2]!~/^[0-9]+$/ || b[2]<b[1] || b[2]-b[1]>100000)))return "null";for(j=b[1]+0;j<=(b[2]==""?b[1]:b[2]);j++){o=o sep sprintf("%.0f",j);sep=","}}return o "]"}
  function stat(p, a,s,n){s=readfile(p "/stat");if(!exists)return 0;sub(/^.*\) /,"",s);n=split(s,a," ");if(n<37 || a[20]!~/^[0-9]+$/)return 0;state=a[1];ppid=a[2]+0;flags=a[7]+0;ut=a[12]+0;st=a[13]+0;start=a[20]+0;cpu=a[37]+0;return 1}
  function status(s,k, a,n,i,v){n=split(s,a,"\n");for(i=1;i<=n;i++)if(index(a[i],k ":")==1){v=substr(a[i],length(k)+2);sub(/^[[:space:]]+/,"",v);return v}return ""}
  function allowed(s,k, v){v=status(s,k);return v=="" && index(s,k ":")==0?"null":cpus(v)}
  function unescape(s){gsub(/\\040/," ",s);gsub(/\\011/,"\t",s);gsub(/\\012/,"\n",s);gsub(/\\134/,"\\",s);return s}
  function mountgroup(rel,controllers,version, lines,n,i,a,j,fs,opts,root,point,best,tail,parts,nparts,k,matchall){
    n=split(mountinfo,lines,"\n");best=-1;cgroot="";cgpath=""
    for(i=1;i<=n;i++){
      split(lines[i],a," ");j=7;while(j<=length(a) && a[j]!="-")j++
      fs=a[j+1];opts="," a[j+3] ","
      if(version==2 && fs!="cgroup2")continue
      if(version==1){
        if(fs!="cgroup")continue
        nparts=split(controllers,parts,",");matchall=1
        for(k=1;k<=nparts;k++)if(index(opts,"," parts[k] ",")==0)matchall=0
        if(!matchall)continue
      }
      root=unescape(a[4]);point=unescape(a[5]);if(root!="/" && rel!=root && index(rel,root "/")!=1)continue
      if(length(root)>best){best=length(root);cgroot=point;tail=(root=="/"?rel:substr(rel,length(root)+1));cgpath=point (tail=="/"?"":tail)}
    }
    return cgroot!=""
  }
  function effective(path,version,which, root,v,controllers){root=cgroot;while(1){
    v=readfile(path "/cpuset." which ".effective");if(exists)return cpus(v)
    v=readfile(path "/cpuset.effective_" which);if(exists)return cpus(v)
    if(version==2){
      # A readable controllers file without cpuset proves this level inherits.
      # Missing/unreadable interfaces with cpuset enabled remain unknown.
      controllers=readfile(path "/cgroup.controllers");if(!exists || (" " controllers " ")~/ cpuset /)return "null"
    }else{v=readfile(path "/cpuset." which);if(!exists)return "null";if(v!="")return cpus(v)}
    if(path==root)break;sub(/\/[^/]+$/,"",path)
  }return "null"}
  function cgroups(cg, lines,n,i,a,v,controllers,rel,path,keys,nk,j,value,row,rows,sep,ver,candidates,k){
    if(cg in cgcache){cgrows=cgcache[cg];effcpu=effcache[cg];effmem=memcache[cg];return}
    rows="[";sep="";effcpu="null";effmem="null";n=split(cg,lines,"\n")
    nk=split("cpu.max cpu.stat cpu.cfs_quota_us cpu.cfs_period_us cpuset.cpus.effective cpuset.mems.effective cpuset.effective_cpus cpuset.effective_mems cpuset.cpus cpuset.mems memory.current memory.max memory.high memory.events memory.swap.current memory.swap.max memory.usage_in_bytes memory.limit_in_bytes memory.failcnt pids.current pids.max pids.events",keys," ")
    for(i=1;i<=n;i++){
      split(lines[i],a,":");controllers=a[2];rel=substr(lines[i],length(a[1])+length(a[2])+3)
      if(rel~/\/\.\.(\/|$)/ || rel~/\/\.(\/|$)/)continue
      if(a[1]=="0")ver=2
      else if(("," controllers ",")~/,(cpu|cpuset|memory|pids),/)ver=1
      else continue
      if(!mountgroup(rel,controllers,ver))continue
      path=cgpath
      if(ver==2 || ("," controllers ",")~/,cpuset,/){effcpu=effective(path,ver,"cpus");effmem=effective(path,ver,"mems")}
      while(1){row="{\"path\":" q(path) ",\"version\":" ver ",\"controllers\":" q(controllers==""?"unified":controllers)
        for(j=1;j<=nk;j++){value=readfile(path "/" keys[j]);if(exists)row=row "," q(keys[j]) ":" q(value)}
        rows=rows sep row "}";sep=",";if(path==cgroot)break;sub(/\/[^/]+$/,"",path);if(length(path)<length(cgroot))break
      }
    }
    cgrows=rows "]";cgcache[cg]=cgrows;effcache[cg]=effcpu;memcache[cg]=effmem
  }
  function mapjson(a, k,o,sep){o="{";sep="";for(k in a){o=o sep q(k) ":" sprintf("%.0f",a[k]);sep=","}return o "}"}
  function numa(p, text,lines,n,i,a,j,b,size,np,k,pol){
    text=readfile(p "/numa_maps");if(!exists){numamissing++;return "{\"available\":false,\"node_pages\":{},\"node_kb\":{},\"unknown_page_size_pages\":{},\"mapping_count\":0}"}
    for(k in pages)delete pages[k];for(k in kb)delete kb[k];for(k in unknown)delete unknown[k];for(k in policies)delete policies[k]
    n=split(text,lines,"\n");np=0;for(i=1;i<=n;i++){if(split(lines[i],a," ")<2)continue;np++;policies[a[2]]++;size=0;for(j=3;j<=length(a);j++)if(a[j]~/^kernelpagesize_kB=/){split(a[j],b,"=");size=b[2]+0}
      for(j=3;j<=length(a);j++)if(a[j]~/^N[0-9]+=[0-9]+$/){split(a[j],b,"=");k=substr(b[1],2);pages[k]+=b[2];if(size)kb[k]+=b[2]*size;else unknown[k]+=b[2]}
    }
    return "{\"available\":true,\"node_pages\":" mapjson(pages) ",\"node_kb\":" mapjson(kb) ",\"unknown_page_size_pages\":" mapjson(unknown) ",\"mapping_count\":" np ",\"policies\":" mapjson(policies) "}"
  }
  function error(id,reason){errcount++;errs=errs (errs==""?"":",") "{\"id\":" q(id) ",\"reason\":" q(reason) "}"}
  function rankenv(p, savedrs,entry,pos,key,value,o,sep){
    savedrs=RS;RS=sprintf("%c",0);o="{";sep=""
    while((getline entry < (p "/environ"))>0){
      pos=index(entry,"=");if(!pos)continue;key=substr(entry,1,pos-1);value=substr(entry,pos+1)
      if(key~/^(RANK|LOCAL_RANK|WORLD_SIZE|LOCAL_WORLD_SIZE|GROUP_RANK|ASCEND_RT_VISIBLE_DEVICES|ASCEND_VISIBLE_DEVICES|CUDA_VISIBLE_DEVICES)$/ && length(value)<=256){o=o sep q(key) ":" q(value);sep=","}
    }
    close(p "/environ");RS=savedrs;return o "}"
  }
  BEGIN{CONVFMT="%.17g";OFMT="%.17g";mountinfo=readfile(pr "/self/mountinfo");for(i=1;i<32;i++)esc[sprintf("%c",i)]=sprintf("\\u%04x",i);begin=stamp();pc=0;tc=0;count=0}
  NR%2==1{type=$0;next}
  {
    path=$0;if(path=="")next
    if(type=="P" || type=="T"){
      id=basename(path)+0;identity_begin=stamp();if(!stat(path)){error(id,"stat_unreadable_or_exited");next}
      saved=start;s=readfile(path "/status");if(!exists){error(id,"status_unreadable_or_exited");next}
      tgid=status(s,"Tgid")+0;if(tgid<=0 || (type=="P" && tgid!=id)){error(id,"invalid_tgid");next}
      cg=readfile(path "/cgroup");source=exists?"task":"leader_fallback";if(type=="T" && !exists)cg=readfile(pr "/" tgid "/cgroup");cgroups(cg)
      row="{\"tgid\":" tgid ",\"starttime\":" sprintf("%.0f",saved) ",\"state\":" q(state) ",\"ppid\":" ppid ",\"flags\":" sprintf("%.0f",flags) ",\"last_cpu\":" cpu ",\"utime_ticks\":" ut ",\"stime_ticks\":" st ",\"cpu_time_sec\":" ((ut+st)/ticks)
      row=row ",\"name\":" q(status(s,"Name")) ",\"namespace_pids\":" cpus(status(s,"NSpid")) ",\"allowed_cpus\":" allowed(s,"Cpus_allowed_list") ",\"cpus_allowed_list\":" q(status(s,"Cpus_allowed_list")) ",\"mems_allowed_list\":" q(status(s,"Mems_allowed_list"))
      row=row ",\"cgroup\":" q(cg) ",\"cgroup_cpu\":" cgrows ",\"cpuset_cpus_effective\":" (type=="T" && source!="task"?"null":effcpu) ",\"cpuset_mems_effective\":" (type=="T" && source!="task"?"null":effmem) ",\"identity_started_at\":" identity_begin
      if(type=="P"){cmd=readfile(path "/cmdline");gsub(sprintf("%c",0)," ",cmd);row=row ",\"pid\":" id ",\"cmdline\":" q(cmd) ",\"rank_env\":" rankenv(path) ",\"threads\":" (status(s,"Threads")+0) ",\"kernel_thread\":" (int(flags/2097152)%2?"true":"false") ",\"numa_maps\":" numa(path)}
      else row=row ",\"tid\":" id ",\"cgroup_source\":" q(source)
      if(!stat(path) || start!=saved){error(id,"identity_changed_during_snapshot");next}
      row=row ",\"identity_verified_at\":" stamp() "}"
      if(type=="P"){pjson[id]=row;pstamp[id]=saved;porder[++pc]=id}else{tjson[++tc]=row;tp[tc]=tgid}
    }else if(type=="F"){
      rel=readfile(path "/related_cpus");if(rel=="")rel=readfile(path "/affected_cpus");id=basename(path)
      if(rel=="" && id=="cpufreq"){parent=path;sub(/\/cpufreq$/,"",parent);rel=substr(basename(parent),4)}
      group=cpus(rel);identity=(group=="[]"?path:group);if(identity in seen)next;seen[identity]=1
      if(id=="cpufreq")id="cpus_" rel
      row="{\"id\":" q(id) ",\"cpus\":" group ",\"path\":" q(path) ",\"unit\":\"kHz\"";errors="";n=split("related_cpus scaling_cur_freq cpuinfo_cur_freq cpuinfo_max_freq scaling_min_freq scaling_max_freq scaling_governor",keys," ")
      for(i=1;i<=n;i++){v=readfile(path "/" keys[i]);if(exists)row=row "," q(keys[i]) ":" (v~/^[0-9]+$/ && keys[i]!="related_cpus" && keys[i]!="scaling_governor"?v:q(v));else errors=errors (errors==""?"":",") q(keys[i]) ":\"missing_or_unreadable\""}
      items=items (count++?",":"") row ",\"errors\":{" errors "}}"
    }else if(type=="I"){
      parent=path;sub(/\/cpuidle\/[^/]+$/,"",parent);row="{\"cpu\":" (substr(basename(parent),4)+0) ",\"state\":" q(basename(path));errors="";n=split("name desc disable latency residency time usage",keys," ")
      for(i=1;i<=n;i++){v=readfile(path "/" keys[i]);if(exists)row=row "," q(keys[i]) ":" (v~/^[0-9]+$/?v:q(v));else errors=errors (errors==""?"":",") q(keys[i]) ":\"missing_or_unreadable\""}
      items=items (count++?",":"") row ",\"errors\":{" errors "}}"
    }else if(type=="N"){
      row="{\"node\":" (substr(basename(path),5)+0) ",\"cpus\":" cpus(readfile(path "/cpulist"));errors="";n=split("cpulist distance meminfo numastat vmstat",keys," ")
      for(i=1;i<=n;i++){v=readfile(path "/" keys[i]);row=row "," q(keys[i] "_raw") ":" (exists?q(v):"null");if(!exists)errors=errors (errors==""?"":",") q(keys[i]) ":\"missing_or_unreadable\""}
      v=readfile(path "/distance");row=row ",\"distance\":" cpus(v);v=readfile(path "/meminfo");n=split(v,lines,"\n");mem="";for(i=1;i<=n;i++){split(lines[i],a," ");if(a[4]~/^[0-9]+$/){sub(/:$/,"",a[3]);mem=mem (mem==""?"":",") q(a[3]) ":" a[4]}}
      items=items (count++?",":"") row ",\"memory_kb\":{" mem "},\"errors\":{" errors "}}"
    }
  }
  END{
    if(kind=="resources"){
      nf=split("stat loadavg meminfo vmstat diskstats pressure/cpu pressure/memory pressure/io sys/fs/file-nr net/dev",rf," ");raw="";count=0
      for(ri=1;ri<=nf;ri++){value=readfile(pr "/" rf[ri]);ok=exists;if(ok)count++;raw=raw (ri>1?",":"") q("/proc/" rf[ri]) ":{\"text\":" (ok?q(value):"null") ",\"status\":" q(ok?"COLLECTED":"UNAVAILABLE") "}"}
      print "{\"schema_version\":1,\"ts\":" begin ",\"end_ts\":" stamp() ",\"clock\":\"boottime\",\"files\":{" raw "}}"
    }else if(kind=="process"){
      ps="";ts="";count=0;for(i=1;i<=pc;i++){id=porder[i];if(!stat(pr "/" id) || start!=pstamp[id]){error(id,"leader_changed_during_snapshot");delete pjson[id];continue}ps=ps (count++?",":"") pjson[id]}
      nt=0;for(i=1;i<=tc;i++)if(tp[i] in pjson)ts=ts (nt++?",":"") tjson[i]
      print "{\"schema_version\":2,\"clock\":\"boottime\",\"clock_ticks\":" ticks ",\"ts\":" begin ",\"end_ts\":" stamp() ",\"processes\":[" ps "],\"threads\":[" ts "],\"errors\":[" errs "]}"
    }else if(kind=="topology")print "{\"schema_version\":1,\"ts\":" begin ",\"online_cpus\":" cpus(readfile(sy "/devices/system/cpu/online")) ",\"online_nodes\":" cpus(readfile(sy "/devices/system/node/online")) ",\"distance_node_order\":" cpus(readfile(sy "/devices/system/node/online")) ",\"nodes\":[" items "]}"
    else print "{\"schema_version\":2,\"ts\":" begin ",\"clock\":\"boottime\",\"" (kind=="frequency"?"policies":"states") "\":[" items "],\"capability\":" q(count?"available":"unsupported_or_unreadable") (kind=="idle"?",\"time_unit\":\"microseconds\",\"usage_unit\":\"entries\"":"") "}"
    print count,errcount+0,numamissing+0 > countfile;close(countfile)
  }' > "$output.tmp" && mv -f -- "$output.tmp" "$output"
}
hb_manifest(){
  local tmp="$SNAP/hostbound/collection_manifest.json.tmp"
  { printf '{"schema_version":1,"collector":"cpu_trace_collect.sh","duration_sec":%s,"minimal":%s,"hostbound":%s,"discover":%s,"entries":[' "$DURATION" "$MINIMAL" "$HOSTBOUND" "$DISCOVER"
    awk 'NR>1{printf ","}{printf "%s",$0}' "$SNAP/hostbound/collection_entries.jsonl"
    printf ']}\n'
  } > "$tmp" && mv -f -- "$tmp" "$SNAP/hostbound/collection_manifest.json"
  cp -- "$SNAP/hostbound/collection_manifest.json" "$SNAP/collection_manifest.json"
}
HB_COLLECTION_GAPS=0
hb_note_gap(){
  local status=$1 item=$2 reason=$3
  reason=${reason//[[:cntrl:]]/ }
  item=${item//[[:cntrl:]]/ }
  printf '[Warn] 采集缺项 [%s] %s · %s\n' "$status" "$item" "${reason:0:240}" >&2
  HB_COLLECTION_GAPS=$((HB_COLLECTION_GAPS+1))
}

hb_entry(){
  local category=$1 status=$2 rel=$3 reason=${4:-} rc=${5:-null} parsed=${6:-null} count=${7:-null} requested=${8:-true} command=${9:-null} command_exists=${10:-null}
  local present=false empty=null size=null source_field=""
  if [[ -n "${11:-}" ]]; then source_field=",\"source\":$(printf '%s' "${11}" | hb_quote)"; fi
  if [[ -n "$rel" && -f "$SNAP/$rel" ]]; then
    present=true;empty=true;[[ -s "$SNAP/$rel" ]] && empty=false;size=$(wc -c < "$SNAP/$rel");size=${size//[[:space:]]/}
  fi
  printf '{"category":"%s","requested":%s,"status":"%s","command":%s,"command_exists":%s,"returncode":%s,"raw_path":%s,"raw_exists":%s,"empty":%s,"size_bytes":%s,"parse_success":%s,"parsed_count":%s,"started_at":"%s","ended_at":"%s","failure_reason":%s%s}\n' \
    "$category" "$requested" "$status" "$command" "$command_exists" "$rc" "$(if [[ -n "$rel" ]]; then printf '%s' "$rel" | hb_quote; else printf null; fi)" "$present" "$empty" "$size" "$parsed" "$count" "${HB_STARTED:-$(hb_now)}" "$(hb_now)" "$(if [[ -n "$reason" ]]; then printf '%s' "$reason" | hb_quote; else printf null; fi)" "$source_field" >> "$SNAP/hostbound/collection_entries.jsonl"
  if [[ "$requested" == true ]]; then
    case "$status" in
      NO_ACTIVE_PROCESS|NOT_REQUESTED) ;;
      COLLECTED)
        if [[ "$empty" == true ]]; then
          hb_note_gap EMPTY_OUTPUT "$rel" 输出为空
        elif [[ "$reason" == partial_process_snapshot:* ]]; then
          hb_note_gap PARTIAL "$rel" "$reason"
        fi ;;
      *) hb_note_gap "$status" "${rel:-$category}" "${reason:-原因未记录}" ;;
    esac
  fi
}
hb_file(){
  local category=$1 source=$2 rel=$3 status=COLLECTED reason="" rc=0
  if [[ "$rel" == */* ]]; then mkdir -p -- "${SNAP}/${rel%/*}"; fi
  if [[ ! -e "$source" ]]; then status=UNSUPPORTED;reason=interface_missing;rc=1
  elif ! cat -- "$source" > "$SNAP/$rel" 2> "$SNAP/hostbound/.read_error"; then
    status=EXECUTION_FAILED;reason=$(cat "$SNAP/hostbound/.read_error");rc=1
    [[ "$reason" == *[Pp]ermission* || "$reason" == *'not permitted'* ]] && status=PERMISSION_DENIED
  fi
  hb_entry "$category" "$status" "$rel" "$reason" "$rc" null null true null null "${4:-}"
}
hb_command(){
  local category=$1 rel=$2;shift 2
  local status=COLLECTED reason="" rc=0 argv="[" sep="" arg
  for arg in "$@"; do argv+="$sep$(printf '%s' "$arg" | hb_quote)";sep=,;done;argv+=']'
  HB_STARTED=$(hb_now)
  if ! command -v "$1" >/dev/null 2>&1; then hb_entry "$category" COMMAND_NOT_FOUND "$rel" "executable_not_found:$1" null null null true "$argv" false;unset HB_STARTED;return 0;fi
  if command -v timeout >/dev/null 2>&1; then timeout -k 2 15 "$@" > "$SNAP/$rel" 2>&1;else "$@" > "$SNAP/$rel" 2>&1;fi;rc=$?
  # Exit 1 with "none" is a successful negative result for this query.
  if ((rc==1)) && [[ "$1" == systemd-detect-virt && "$2" == --container && "$(< "$SNAP/$rel")" == none ]]; then
    :
  elif ((rc));then
    reason=$(tail -c 2000 "$SNAP/$rel");status=EXECUTION_FAILED
    [[ "$reason" == *[Pp]ermission* || "$reason" == *'not permitted'* || "$reason" == *'Access denied'* ]] && status=PERMISSION_DENIED
    [[ "$reason" == *[Uu]nsupported* || "$reason" == *'not supported'* || "$reason" == *'invalid option'* || "$reason" == *'Invalid argument'* ]] && status=UNSUPPORTED
    ((rc==124 || rc==137)) && reason=command_timed_out
  fi
  hb_entry "$category" "$status" "$rel" "$reason" "$rc" null null true "$argv" true
  unset HB_STARTED
}
hb_data(){
  local kind=$1 category=$2 rel=$3 count errors missing reason="" status=COLLECTED parsed=true
  HB_STARTED=$(hb_now)
  if hb_snapshot "$kind" "$SNAP/$rel"; then
    read -r count errors missing < "$SNAP/hostbound/.snapshot_count"
    [[ "$count" == 0 ]] && { status=UNSUPPORTED;[[ "$kind" == process ]] && status=NO_ACTIVE_PROCESS; }
    if [[ "$kind" == process ]];then
      HB_PROCESS_COUNT=$count;HB_NUMA_MISSING=$missing
      if ((errors>0));then reason="partial_process_snapshot:$errors";((count==0)) && { status=EXECUTION_FAILED;parsed=false; };fi
    fi
    hb_entry "$category" "$status" "$rel" "$reason" 0 "$parsed" "$count"
  else hb_entry "$category" EXECUTION_FAILED "$rel" snapshot_failed 1 false;fi
  unset HB_STARTED
}
hb_environment_launch(){
  set -o pipefail
  head -c 1048577 -- "$1" | LC_ALL=C awk '
    BEGIN { RS=sprintf("%c",0) }
    {
      bytes+=length($0)+1
      if(bytes>1048576) exit 3
      pos=index($0,"=")
      if(!pos) next
      key=substr($0,1,pos-1)
      val=substr($0,pos+1)
      if(length(val)>256) next
      if(key~/^(RANK|LOCAL_RANK|WORLD_SIZE|LOCAL_WORLD_SIZE|GROUP_RANK|RANK_ID|RANK_SIZE|DEVICE_ID|MKL_NUM_THREADS|OPENBLAS_NUM_THREADS|HCCL_BUFFSIZE|HCCL_CONNECT_TIMEOUT|HCCL_EXEC_TIMEOUT|TASK_QUEUE_ENABLE|ASCEND_LAUNCH_BLOCKING)$/ && val~/^[0-9]+$/ ||
         key~/^(OMP_NUM_THREADS|ASCEND_RT_VISIBLE_DEVICES|ASCEND_VISIBLE_DEVICES|CUDA_VISIBLE_DEVICES)$/ && val~/^[0-9]+([,-][0-9]+)*$/ ||
         key=="GOMP_CPU_AFFINITY" && val~/^[0-9]+([ ,:-][0-9]+)*$/ ||
         key=="OMP_WAIT_POLICY" && tolower(val)~/^(active|passive)$/ ||
         key=="OMP_PROC_BIND" && tolower(val)~/^(true|false|primary|master|close|spread)(,(primary|master|close|spread))*$/)
        print key "=" val
    }'
}

hb_environment_libraries(){
  set -o pipefail
  head -c 4194305 -- "$1" | LC_ALL=C awk '
    {
      bytes+=length($0)+1
      if(bytes>4194304) exit 3
      if(!sub(/^[^ ]+ +[^ ]+ +[^ ]+ +[^ ]+ +[^ ]+ +/,"")) next
      if($0~/^\/.*\.so([.][^\/[:space:]]+)*( \(deleted\))?$/ && !seen[$0]++){
        output+=length($0)+1
        if(output>65536) exit 3
        print
      }
    }'
}

hb_environment_field(){
  local file=$1 value="" status=COLLECTED reason="" rc=0 stderr="$SNAP/hostbound/.environment_error"
  shift
  value=$("$@" "$file" 2>"$stderr") || rc=$?
  if ((rc)); then
    status=EXECUTION_FAILED; reason=read_failed
    if ((rc==3)); then reason=size_limit_exceeded
    elif LC_ALL=C grep -Eqi 'permission denied|operation not permitted' "$stderr"; then status=PERMISSION_DENIED
    elif [[ ! -e "$file" && ! -L "$file" ]]; then status=UNSUPPORTED; reason=interface_missing
    fi
    value=""
  fi
  printf '{"status":"%s","source":%s,"reason":%s,"text":%s}' "$status" \
    "$(printf '%s' "$file" | hb_quote)" "$(printf '%s' "$reason" | hb_quote)" \
    "$(if ((rc)); then printf null; else printf '%s' "$value" | hb_quote; fi)"
}

hb_environment_pid(){
  local pid=$1 dir="$HB_PROC/$1" rel="hostbound/environment/pid_$1.json" start end
  local stat_start='sub(/^.*\) /,"") && $20~/^[0-9]+$/ {print $20; exit}'
  local HB_STARTED
  HB_STARTED=$(hb_now)
  start=$(awk "$stat_start" "$dir/stat" 2>/dev/null)
  if [[ -z "$start" || "$(awk '$1=="Tgid:"{print $2;exit}' "$dir/status" 2>/dev/null)" != "$pid" ]]; then
    hb_entry environment_process EXECUTION_FAILED "$rel" target_identity_unavailable 1
    return
  fi
  if {
    printf '{"pid":%s,"starttime":"%s","environment":' "$pid" "$start"
    hb_environment_field "$dir/environ" hb_environment_launch
    printf ',"libraries":'; hb_environment_field "$dir/maps" hb_environment_libraries
    printf ',"limits":'; hb_environment_field "$dir/limits" cat --
    printf ',"exe":'; hb_environment_field "$dir/exe" readlink --
    printf '}\n'
  } > "$SNAP/$rel.tmp"; then
    end=$(awk "$stat_start" "$dir/stat" 2>/dev/null)
    if [[ "$start" == "$end" ]] && mv -f -- "$SNAP/$rel.tmp" "$SNAP/$rel"; then
      hb_entry environment_process COLLECTED "$rel" "" 0
      return
    fi
  fi
  rm -f -- "$SNAP/$rel.tmp"
  hb_entry environment_process EXECUTION_FAILED "$rel" target_identity_changed_or_write_failed 1
}

hb_install_prefix(){
  local file=$1 key=$2
  [[ -f "$file" && -r "$file" ]] || return
  # The installer record is data. Read only the requested absolute path.
  awk -v key="$key" '
    sub("^[[:space:]]*" key "[[:space:]]*=[[:space:]]*", "") {
      sub(/[[:space:]]+$/, "")
      if ($0 ~ /^".*"$/ || $0 ~ /^\047.*\047$/) $0=substr($0,2,length($0)-2)
      if ($0 ~ /^\// && $0 !~ /[[:cntrl:]]/) { print; exit }
    }' "$file"
}

hb_ascend_version_file(){
  local rel="hostbound/environment/ascend/$1.txt" candidate non_regular=""
  local -A cseen=()
  shift
  for candidate in "$@"; do
    [[ -n "${cseen[$candidate]+x}" ]] && continue
    cseen[$candidate]=1
    if [[ -f "$candidate" ]]; then
      hb_file environment_ascend "$candidate" "$rel" "$candidate"
      return
    fi
    if [[ -z "$non_regular" && ( -e "$candidate" || -L "$candidate" ) ]]; then
      non_regular=$candidate
    fi
  done
  if [[ -n "$non_regular" ]]; then
    hb_entry environment_ascend UNSUPPORTED "$rel" version_source_not_regular 1 null null true null null "$non_regular"
  else
    hb_entry environment_ascend UNSUPPORTED "$rel" interface_missing 1 null null true null null "$1"
  fi
}

hb_ascend_versions(){
  local etc=$1 ascend=$2 prefix dir config driver arch id suffix ambiguous="" atb_home llm_home
  local -a prefixes=() roots=() versions=() candidates=() suffixes=()
  if [[ ${CONDA_PREFIX:-} == /* && -d "$CONDA_PREFIX/Ascend" ]]; then
    prefixes+=("${CONDA_PREFIX%/}/Ascend")
  fi
  if [[ ${HOME:-} == /* ]]; then
    config=$(hb_install_prefix "$HOME/Ascend/ascend_cann_install.info" Install_Path)
    [[ -n "$config" ]] && prefixes+=("${config%/}")
  fi
  config=$(hb_install_prefix "$etc/Ascend/ascend_cann_install.info" Install_Path)
  [[ -n "$config" ]] && prefixes+=("${config%/}")
  prefixes+=("$ascend")
  [[ ${HOME:-} == /* && -d "$HOME/Ascend" ]] && prefixes+=("${HOME%/}/Ascend")

  # Select one installation before probing its components. An active prefix
  # may expose both the new and old entry points.
  for dir in "${ASCEND_HOME_PATH:-}" "${ASCEND_TOOLKIT_HOME:-}"; do
    if [[ "$dir" == /* && -d "$dir" ]]; then roots+=("${dir%/}"); break; fi
  done
  if ((${#roots[@]} == 0)); then
    for prefix in "${prefixes[@]}"; do
      for dir in "$prefix/cann" "$prefix/ascend-toolkit/latest"; do
        [[ -d "$dir" ]] && roots+=("$dir")
      done
      ((${#roots[@]})) && break
      for dir in "$prefix"/cann-[0-9]* "$prefix"/ascend-toolkit/[0-9]* "$prefix/nnrt/latest" "$prefix/nnae/latest"; do
        [[ -d "$dir" ]] || continue
        [[ ${#versions[@]} -gt 0 && "$dir" -ef "${versions[0]}" ]] && continue
        versions+=("$dir")
        ((${#versions[@]} > 1)) && break
      done
      if ((${#versions[@]})); then
        if ((${#versions[@]} == 1)); then roots=("${versions[0]}"); else ambiguous=$prefix; fi
        break
      fi
    done
  fi
  if ((${#roots[@]} == 0)); then roots=("${prefixes[0]}/cann" "${prefixes[0]}/ascend-toolkit/latest"); fi
  driver=$(hb_install_prefix "$etc/ascend_install.info" Driver_Install_Path_Param)
  arch=$(uname -m)
  atb_home=${ATB_HOME_PATH%/}
  llm_home=${MINDIE_LLM_HOME_PATH%/}
  for id in driver toolkit runtime compiler hccl opp atb mindie; do
    candidates=()
    case "$id" in
      driver)
        [[ -n "$driver" ]] && candidates+=("${driver%/}/driver/version.info")
        candidates+=("$ascend/driver/version.info");;
      atb)
        case "$atb_home" in /*/atb/cxx_abi_[01]) candidates+=("${atb_home%/atb/cxx_abi_?}/version.info");; esac
        for prefix in "${prefixes[@]}"; do
          candidates+=("$prefix/nnal/atb/latest/version.info" "$prefix/atb/latest/version.info")
        done;;
      mindie)
        case "$llm_home" in /*/mindie-llm) candidates+=("${llm_home%/mindie-llm}/version.info");; esac
        for prefix in "${prefixes[@]}"; do candidates+=("$prefix/mindie/latest/version.info"); done;;
      *)
        if [[ "$id" == opp && ${ASCEND_OPP_PATH:-} == /* && -d "$ASCEND_OPP_PATH" ]]; then
          candidates+=("${ASCEND_OPP_PATH%/}/version.info")
        fi
        if [[ -n "$ambiguous" ]]; then
          if ((${#candidates[@]})); then
            hb_ascend_version_file "$id" "${candidates[@]}"
          else
            hb_entry environment_ascend UNSUPPORTED "hostbound/environment/ascend/$id.txt" ambiguous_cann_installation 1 null null true null null "$ambiguous"
          fi
          continue
        fi
        suffixes=("$id/version.info")
        if [[ "$id" == toolkit ]]; then
          case "$arch" in aarch64|x86_64) suffixes+=("$arch-linux/ascend_toolkit_install.info");; esac
          suffixes+=("asc-devkit/version.info" "share/info/asc-devkit/version.info")
        else
          suffixes+=("share/info/$id/version.info")
        fi
        for suffix in "${suffixes[@]}"; do
          for dir in "${roots[@]}"; do candidates+=("$dir/$suffix"); done
        done;;
    esac
    hb_ascend_version_file "$id" "${candidates[@]}"
  done
}

hb_environment(){
  local etc=$1 ascend=$2 root=hostbound/environment id path pid os_release
  local -A seen=()
  mkdir -p -- "$SNAP/$root/host" "$SNAP/$root/ascend" || return 1
  os_release="$etc/os-release"
  if [[ ! -e "$os_release" && "$etc" == /etc && -f /usr/lib/os-release ]]; then os_release=/usr/lib/os-release; fi
  hb_file environment_host "$os_release" "$root/host/os_release.txt" "$os_release"
  hb_command environment_host "$root/host/kernel.txt" uname -srmo
  for path in "$HB_SYS/kernel/mm/transparent_hugepage/enabled" "$HB_PROC/sys/kernel/numa_balancing" \
      "$HB_PROC/sys/vm/swappiness" "$HB_PROC/sys/vm/overcommit_memory" \
      "$HB_SYS/devices/system/clocksource/clocksource0/current_clocksource"; do
    id=${path##*/}
    case "$id" in enabled) id=thp;; current_clocksource) id=clocksource;; esac
    hb_file environment_host "$path" "$root/host/$id.txt" "$path"
  done
  hb_ascend_versions "$etc" "$ascend"
  if ((HOSTBOUND)) && [[ -n "$PID_LIST" ]]; then
    for pid in ${PID_LIST//,/ }; do
      [[ -n "${seen[$pid]+x}" ]] && continue
      seen[$pid]=1
      hb_environment_pid "$pid"
    done
  else
    hb_entry environment_process NOT_REQUESTED "" explicit_host_pid_required null null null false
  fi
  rm -f -- "$SNAP/hostbound/.environment_error"
}

# Generated from the sibling Ascend Dump skill by update_ascend_dump_bundle.py.
hb_write_bundled_ascend_dump(){
  python3 -c 'import base64, gzip, sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(gzip.decompress(base64.b64decode(sys.stdin.buffer.read())))' "$1" <<'MSPRECHECKER_PAYLOAD'
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
MSPRECHECKER_PAYLOAD
}

hb_ascend_dump(){
  local script=$1 source=$1 rel=hostbound/environment/msprechecker_dumped.json
  local pid rc=0 export_tmp="" bundled=false HB_STARTED
  local -a args=(--filter --no-probes)
  local -A seen=()
  HB_STARTED=$(hb_now)
  if [[ -z "$script" ]]; then
    source=bundled:msprechecker_dump.py
    bundled=true
  elif [[ ! -f "$script" || ! -r "$script" ]]; then
    hb_entry environment_dump EXECUTION_FAILED "$rel" collector_script_missing_or_unreadable 1 null null true null null "$script"
    warn "无法读取 Ascend Dump 采集脚本: $script"
    return
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    hb_entry environment_dump COMMAND_NOT_FOUND "$rel" python3_not_found null null null true '["python3"]' false "$source"
    return
  fi
  if ((HOSTBOUND)); then
    for pid in ${PID_LIST//,/ }; do
      [[ -n "${seen[$pid]+x}" ]] && continue
      seen[$pid]=1
      args+=(--target "pid-$pid=$pid")
    done
  fi
  if ! mkdir -p -- "$SNAP/hostbound/environment"; then
    hb_entry environment_dump EXECUTION_FAILED "$rel" dump_directory_failed 1
    return
  fi
  if [[ "$bundled" == true ]]; then
    script="$SNAP/hostbound/environment/.msprechecker_dump.py"
    if ! (umask 077; hb_write_bundled_ascend_dump "$script") > "$SNAP/hostbound/environment/ascend_dump_log.txt" 2>&1; then
      rm -f -- "$script"
      hb_entry environment_dump EXECUTION_FAILED "$rel" bundled_collector_unavailable_check_ascend_dump_log 1 null null true null null "$source"
      return
    fi
  fi
  (umask 077; python3 -- "$script" "${args[@]}" --output-path "$SNAP/$rel.tmp") \
    > "$SNAP/hostbound/environment/ascend_dump_log.txt" 2>&1 || rc=$?
  if [[ "$bundled" == true ]]; then rm -f -- "$script"; fi
  if ((rc)) || [[ ! -s "$SNAP/$rel.tmp" ]] || ! mv -f -- "$SNAP/$rel.tmp" "$SNAP/$rel"; then
    rm -f -- "$SNAP/$rel.tmp"
    ((rc)) || rc=1
    hb_entry environment_dump EXECUTION_FAILED "$rel" native_dump_failed_check_ascend_dump_log "$rc" null null true null null "$source"
    warn "Ascend Dump 采集失败，见 $SNAP/hostbound/environment/ascend_dump_log.txt"
    return
  fi
  hb_entry environment_dump COLLECTED "$rel" "" 0 null null true null null "$source"
  local output="$OUTDIR/${CAPTURE_NAME}_msprechecker_dumped.json"
  if export_tmp=$(mktemp "$OUTDIR/.${CAPTURE_NAME}_dump_XXXXXX") &&
      cp -- "$SNAP/$rel" "$export_tmp" && mv -f -- "$export_tmp" "$output"; then
    ok "Ascend Dump JSON: $output"
  else
    [[ -n "$export_tmp" ]] && rm -f -- "$export_tmp"
    warn "无法写出独立 JSON，原生快照已保留: $SNAP/$rel"
  fi
}

hb_phase(){
  local phase=$1 name rel suffix="" tool p node context=unknown detector pid f
  [[ "$phase" == end ]] && suffix=_at_end
  for name in stat interrupts softirqs schedstat;do
    rel="$name.txt";[[ "$name" == stat ]] && rel=proc_stat.txt
    [[ "$phase" == end ]] && rel="hostbound/$name$suffix.txt"
    case "$name" in stat) p=proc_stat;;interrupts)p=irq;;softirqs)p=softirq;;*)p=schedstat;;esac
    hb_file "$p" "$HB_PROC/$name" "$rel"
  done
  if [[ "$phase" == start ]];then
    for name in cpuinfo loadavg meminfo vmstat cmdline;do rel="$name.txt";[[ "$name" == cmdline ]] && rel=hostbound/kernel_cmdline.txt;hb_file host_context "$HB_PROC/$name" "$rel";done
    hb_command product_identity hostbound/dmi_product_name.txt cat "$HB_SYS/class/dmi/id/product_name"
    hb_file cpu_topology "$HB_SYS/devices/system/cpu/online" hostbound/cpu_online.txt
    hb_data topology cpu_topology hostbound/numa_topology.json
    for p in "$HB_SYS"/devices/system/node/online "$HB_SYS"/devices/system/node/node[0-9]*/{cpulist,distance,meminfo}; do
      [[ -e "$p" ]] && hb_file cpu_topology "$p" "hostbound/sysfs/node/${p#"$HB_SYS/devices/system/node/"}"
    done
    hb_command cpu_topology hostbound/lscpu.txt lscpu
    hb_command cpu_topology hostbound/lscpu_extended.txt lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE
    hb_command cpu_topology hostbound/lscpu_parse.txt lscpu -p=CPU,CORE,SOCKET,NODE,ONLINE
    hb_command cpu_topology hostbound/numactl.txt numactl -H
    hb_command cpu_topology hostbound/numastat.txt numastat
    hb_command cpu_topology hostbound/numastat_memory.txt numastat -m
    hb_command host_context hostbound/container_detector.txt systemd-detect-virt --container
    detector=$(cat "$SNAP/hostbound/container_detector.txt" 2>/dev/null)
    [[ "$detector" == none ]] && context=host
    [[ -n "$detector" && "$detector" != none && "$detector" =~ ^[a-zA-Z0-9_-]+$ ]] && context=container
    [[ -e /.dockerenv || -e /run/.containerenv ]] && context=container
    { printf 'execution_context=%s\nboot_id=%s\ncollector_pid=%s\npid_namespace=%s\ninit_pid_namespace=%s\n' "$context" "$(cat "$HB_PROC/sys/kernel/random/boot_id" 2>/dev/null)" "$$" "$(readlink "$HB_PROC/self/ns/pid" 2>/dev/null)" "$(readlink "$HB_PROC/1/ns/pid" 2>/dev/null)"; } > "$SNAP/hostbound/host_context.txt"
    hb_entry host_context COLLECTED hostbound/host_context.txt "" 0 true 1
    hb_environment /etc /usr/local/Ascend
    for tool in gil_tracer function_monitor msprof host_analyzer;do hb_entry external_tools NOT_REQUESTED "" "external_tool:$tool" null null null false;done
  fi
  hb_data resources resources "hostbound/resource_$phase.json"
  if [[ "$phase" == start ]];then
    mkdir -p -- "$SNAP/hostbound/resources"
    hb_command resources hostbound/resources/df_blocks.txt df -Pk
    hb_command resources hostbound/resources/df_inodes.txt df -Pi
    hb_command resources hostbound/resources/lsblk.txt lsblk -b -P -o NAME,SIZE,TYPE,ROTA,MOUNTPOINT
    hb_file resources "$HB_PROC/self/mountinfo" hostbound/resources/mountinfo.txt
  fi
  if [[ "$phase" == end ]];then
    hb_command resources hostbound/resources/df_blocks_end.txt df -Pk
    hb_command resources hostbound/resources/df_inodes_end.txt df -Pi
  fi
  hb_data frequency frequency "hostbound/frequency_$phase.json"
  hb_data idle idle "hostbound/idle_$phase.json"
  if ((HOSTBOUND));then
    hb_data process processes "hostbound/process_$phase.json"
    hb_command processes "hostbound/ps_$phase.txt" ps -e -o pid,ppid,psr,stat,comm,args
    hb_command processes "hostbound/pstree_$phase.txt" pstree -p
    rel=hostbound/npu_smi_info.txt;[[ "$phase" == start ]] && rel=hostbound/npu_smi_info_start.txt
    hb_command npu_info "$rel" npu-smi info
    # Raw vendor tables are parsed offline; never equate unknown format with no tasks.
    [[ "$phase" == start && -f "$SNAP/$rel" ]] && cp -- "$SNAP/$rel" "$SNAP/hostbound/npu_smi_info.txt"
    if [[ "$phase" == start ]];then
      hb_command npu_mapping hostbound/npu_smi_map.txt npu-smi info -m
      hb_command npu_topology hostbound/npu_smi_topology.txt npu-smi info -t topo
      hb_command product_identity hostbound/npu_smi_product.txt npu-smi info -t product -i 0 -c 0
    fi
    # All processes (including NPU workers and descendants) have NUMA page summaries
    # in process_*.json. Explicit roots additionally retain complete raw maps.
    p=COLLECTED
    ((HB_PROCESS_COUNT==0 || HB_NUMA_MISSING>=HB_PROCESS_COUNT)) && p=EXECUTION_FAILED
    hb_entry numa_process "$p" "hostbound/process_$phase.json" "numa_maps_unavailable:${HB_NUMA_MISSING:-0};raw_maps_for_explicit_pids" 0 null
    for pid in ${PID_LIST//,/ };do
      for f in status cgroup numa_maps stat cmdline;do hb_file numa_process "$HB_PROC/$pid/$f" "hostbound/pid_${pid}_${f}_${phase}.txt";done
      hb_command numa_process "hostbound/pid_${pid}_numastat_${phase}.txt" numastat -p "$pid"
      hb_command processes "hostbound/pid_${pid}_affinity_${phase}.txt" taskset -pc "$pid"
    done
  else
    if [[ "$phase" == start ]];then
      hb_entry product_identity NOT_REQUESTED hostbound/npu_smi_product.txt disabled_by_no_hostbound null null null false
    fi
    for p in processes npu_info npu_mapping npu_topology numa_process;do hb_entry "$p" NOT_REQUESTED "" disabled_by_no_hostbound null null null false;done
  fi
  hb_manifest
}
record_trace_status(){
  local status=$1 reason=${2:-} rel category lost=""
  if [[ "$status" == COLLECTED && ! -s "$SNAP/trace.txt" ]];then status=PARSE_FAILED;reason=empty_trace_export;fi
  if [[ "$status" == COLLECTED && -s "$SNAP/hostbound/export_errors.txt" ]];then
    status=EXECUTION_FAILED;reason=trace_export_incomplete_check_export_errors
  fi
  printf '%s: %s\n' "$status" "$reason" > "$SNAP/hostbound/trace_error.txt"
  hb_entry trace "$status" trace.txt "$reason"
  for rel in hostbound/frequency_samples.jsonl hostbound/resource_samples.jsonl hostbound/capabilities.tsv;do
    category=frequency;[[ "$rel" == *resource_samples* ]] && category=resources;[[ "$rel" == *capabilities* ]] && category=trace_capabilities
    if [[ -f "$SNAP/$rel" ]];then hb_entry "$category" COLLECTED "$rel";else hb_entry "$category" "$([[ "$status" == COLLECTED ]] && echo EXECUTION_FAILED || echo "$status")" "$rel" not_generated;fi
  done
  if [[ -f "$SNAP/trace_overrun.txt" ]]; then
    lost=$(< "$SNAP/trace_overrun.txt")
    if [[ "$lost" =~ ^[0-9]+$ && "$lost" != 0 ]]; then
      hb_note_gap LOST_EVENTS trace_overrun.txt "记录丢失或溢出 $lost 条事件"
    elif [[ ! "$lost" =~ ^[0-9]+$ ]]; then
      hb_entry trace_stats UNSUPPORTED trace_overrun.txt trace_loss_stats_unavailable
    fi
  fi
  hb_manifest
  if ((HB_COLLECTION_GAPS)); then
    printf '[Warn] 采集缺项摘要，共 %d 项。记录见 %s/collection_manifest.json\n' \
      "$HB_COLLECTION_GAPS" "$SNAP" >&2
  fi
}
hb_poll(){
  while [[ ! -e "$SNAP/hostbound/poll.stop" ]];do
    hb_snapshot frequency "$SNAP/hostbound/.frequency_poll.json" || return 1
    cat "$SNAP/hostbound/.frequency_poll.json" >> "$SNAP/hostbound/frequency_samples.jsonl"
    hb_snapshot resources "$SNAP/hostbound/.resource_poll.json" || return 1
    cat "$SNAP/hostbound/.resource_poll.json" >> "$SNAP/hostbound/resource_samples.jsonl"
    sleep "$FREQ_INTERVAL"
  done
}
# END standalone evidence

# ---------- 参数解析 ----------
DURATION=3; OUTDIR="."; BUFFER_SIZE=16384; CPU_LIST=""; MINIMAL=0; PID_LIST=""; HOSTBOUND=1; DISCOVER=1; FREQ_INTERVAL=1
ASCEND_DUMP=1; ASCEND_DUMP_SCRIPT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--duration|-o|--output|-b|--buffer-size|-c|--cpu-list|-p|--pid|--frequency-interval|--ascend-dump-script)
      [[ $# -ge 2 && "$2" != --* ]] || { err "missing option value (缺少参数): $1"; exit 1; };;
  esac
  case "$1" in
    -t|--duration)    DURATION="$2"; shift 2;;
    -o|--output)      OUTDIR="$2"; shift 2;;
    -b|--buffer-size) BUFFER_SIZE="$2"; shift 2;;
    -c|--cpu-list)    CPU_LIST="$2"; shift 2;;
    --full) MINIMAL=0; shift;;
    --discover) DISCOVER=1; HOSTBOUND=1; shift;;
    --frequency-interval) FREQ_INTERVAL="$2"; shift 2;;
    --ascend-dump-script) ASCEND_DUMP=1; ASCEND_DUMP_SCRIPT="$2"; shift 2;;
    --no-ascend-dump) ASCEND_DUMP=0; shift;;
    -m|--minimal)     MINIMAL=1; shift;;
    -p|--pid)         PID_LIST="$2"; HOSTBOUND=1; shift 2;;
    --hostbound)      HOSTBOUND=1; shift;;
    --no-hostbound)   HOSTBOUND=0; DISCOVER=0; shift;;
    -h|--help)        usage; exit 0;;
    *) err "未知参数: $1"; usage; exit 1;;
  esac
done
if ! awk -v x="$FREQ_INTERVAL" 'BEGIN {exit !(x ~ /^[0-9]+([.][0-9]+)?$/ && x>=0.2)}'; then
  err "frequency-interval 必须 >=0.2 秒"; exit 1
fi
[[ -z "$CPU_LIST" || "$CPU_LIST" =~ ^[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$ ]] || { err "CPU列表格式错误"; exit 1; }
if [[ "$DURATION" =~ ^[0-9]+$ ]] && [[ "$BUFFER_SIZE" =~ ^[0-9]+$ ]] && (( DURATION>=1 && 10#$BUFFER_SIZE>=1 )); then :; else
  err "时长和 buffer 必须是 ≥1 的纯数字"; exit 1; fi
# PID 合法性: 逗号分隔的正整数 (不校验进程是否存在, 采集阶段自动跳过)
(( HOSTBOUND )) && DISCOVER=1
for _p in ${PID_LIST//,/ }; do
  [[ "$_p" =~ ^[1-9][0-9]*$ ]] || { err "pid 必须为正整数: $_p"; exit 1; }
done
# 创建证据目录与只读侧车在 tracefs/root 探测之前；降级结果也必须可审计。
PHASE_TOTAL=5
phase_begin "采集只读能力、拓扑与进程前置证据"
mkdir -p -- "$OUTDIR" || exit 1
SNAP=$(mktemp -d "$OUTDIR/cpu_trace_$(date +%Y%m%d_%H%M%S)_XXXXXX") || { err "无法创建采集目录: $OUTDIR"; exit 1; }
CAPTURE_NAME=${SNAP##*/}
mkdir -p -- "$SNAP/hostbound" || exit 1
HB_TICKS=$(getconf CLK_TCK 2>/dev/null || echo 100)
: > "$SNAP/hostbound/collection_entries.jsonl"
if (( ASCEND_DUMP )) && { (( HOSTBOUND )) || [[ -n "$ASCEND_DUMP_SCRIPT" ]]; }; then
  hb_ascend_dump "$ASCEND_DUMP_SCRIPT"
else
  hb_entry environment_dump NOT_REQUESTED "" disabled_by_collection_options null null null false
fi
hb_phase start
phase_end "前置证据状态已保存: $SNAP/hostbound/collection_manifest.json"
if [[ "$EUID" -ne 0 ]]; then
  record_trace_status PERMISSION_DENIED root_required_for_private_ftrace_instance
  err "请使用 root 权限运行: sudo bash $0；只读证据已保留: $SNAP"; exit 1; fi
# 阶段总数: 前置证据/兼容快照/采集/导出/打包。

# ---------- 定位 tracefs ----------
TRACE_DIR=""
for d in /sys/kernel/tracing /sys/kernel/debug/tracing; do
  [[ -d "$d" ]] && TRACE_DIR="$d" && break
done
if [[ -z "$TRACE_DIR" ]]; then
  record_trace_status UNSUPPORTED tracefs_not_found
  err "未找到 tracefs/debugfs；只读证据已保留: $SNAP"; exit 1; fi
ok "使用 tracing 目录: $TRACE_DIR"
# per_cpu stats 可读时, 采集进度条额外展示已捕获事件数/速率/丢弃告警
STATS_OK=0; compgen -G "$TRACE_DIR/per_cpu/cpu*/stats" >/dev/null 2>&1 && STATS_OK=1
if [[ ! -w "$TRACE_DIR/tracing_on" ]]; then
  record_trace_status PERMISSION_DENIED tracefs_not_writable
  err "tracing 目录不可写, 请确认 root 权限"; exit 1; fi

# 独立 instance 避免破坏其他诊断工具的 events、buffer 和原始 trace。
TRACE_BASE="$TRACE_DIR"
TRACE_DIR="$TRACE_BASE/instances/cpu_host_$$"
INSTANCE_CREATED=0
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
CPU_MASK=""
if [[ -n "$CPU_LIST" ]]; then CPU_MASK=$(to_mask "$CPU_LIST"); fi

# ---------- 事件集合 ----------
if [[ "$MINIMAL" -eq 1 ]]; then
  EVENT_LIST="sched/sched_switch"
else
  EVENT_LIST="sched/sched_migrate_task sched/sched_wakeup sched/sched_waking sched/sched_switch \
sched/sched_wakeup_new task/task_newtask sched/sched_process_fork sched/sched_process_exec sched/sched_process_exit irq/irq_handler_entry irq/irq_handler_exit \
irq/softirq_entry irq/softirq_exit irq/softirq_raise power/cpu_idle power/cpu_frequency"
fi

# ---------- 私有 instance 清理（包括失败/信号/正常退出） ----------
FREQ_PID=""; CLEANED=0
cleanup() {
  (( CLEANED )) && return 0
  CLEANED=1
  [[ -n "$FREQ_PID" ]] && { kill "$FREQ_PID" 2>/dev/null; wait "$FREQ_PID" 2>/dev/null; }
  if [[ "$INSTANCE_CREATED" == 1 ]]; then
    echo 0 > "$TRACE_DIR/tracing_on" 2>/dev/null
    echo 0 > "$TRACE_DIR/events/enable" 2>/dev/null
    rmdir "$TRACE_DIR" 2>/dev/null || warn "独立 trace instance 清理失败: $TRACE_DIR"
  fi
}
abort(){
  progress_clear
  for j in $(jobs -pr 2>/dev/null); do kill "$j" 2>/dev/null; done
  record_trace_status EXECUTION_FAILED collection_interrupted
  err "采集被中断，清理独立 instance，保留已写入的证据"
  exit 130
}
trap cleanup EXIT
trap abort INT TERM
mkdir "$TRACE_DIR" 2>/dev/null || {
  record_trace_status UNSUPPORTED private_trace_instance_unavailable
  err "内核/权限不支持独立 trace instance；只读证据已保留: $SNAP"; exit 1;
}
INSTANCE_CREATED=1
ENABLED_EVENTS=""
CAPS="$SNAP/hostbound/capabilities.tsv"
printf 'event\texists\twritable\trequested\tenabled\treason\n' > "$CAPS"
[[ -n "$CPU_MASK" ]] && { echo "$CPU_MASK" > "$TRACE_DIR/tracing_cpumask" || { record_trace_status PERMISSION_DENIED tracing_cpumask_write_failed; exit 1; }; }
# /proc/uptime 使用 boottime；仅 boot trace clock 与其对齐。
TRACE_CLOCK="unknown"
if grep -qw boot "$TRACE_DIR/trace_clock"; then
  echo boot > "$TRACE_DIR/trace_clock" && TRACE_CLOCK="boot"
fi
printf '%s\n' "$TRACE_CLOCK" > "$SNAP/hostbound/trace_clock.txt"

# ---------- 环境初始化 ----------
echo 0 > "$TRACE_DIR/tracing_on" 2>/dev/null
echo nop > "$TRACE_DIR/current_tracer" 2>/dev/null
if ! { printf '%s\n' "$BUFFER_SIZE" > "$TRACE_DIR/buffer_size_kb"; } 2>/dev/null; then
  warn "未能写入 $BUFFER_SIZE KiB/CPU 缓冲区，请检查内存与 tracefs"
fi
BUFFER_EFFECTIVE=$(cat "$TRACE_DIR/buffer_size_kb" 2>/dev/null || echo unknown)
if [[ "$BUFFER_EFFECTIVE" != "$BUFFER_SIZE" ]]; then
  warn "请求 buffer $BUFFER_SIZE KiB/CPU，实际读回 $BUFFER_EFFECTIVE KiB/CPU"
else
  ok "buffer_size_kb = $BUFFER_EFFECTIVE"
fi
echo > "$TRACE_DIR/trace" 2>/dev/null

for ev in $EVENT_LIST; do
  exists=0; writable=0; enabled=0; reason="unsupported"
  if [[ -f "$TRACE_DIR/events/$ev/enable" ]]; then
    exists=1; reason="permission_or_enable_failed"
    [[ -w "$TRACE_DIR/events/$ev/enable" ]] && writable=1
    if echo 1 > "$TRACE_DIR/events/$ev/enable" 2>/dev/null && [[ "$(cat "$TRACE_DIR/events/$ev/enable")" == 1 ]]; then
      enabled=1; reason="ok"; ENABLED_EVENTS="$ENABLED_EVENTS $ev"
    fi
  fi
  printf '%s\t%s\t%s\t1\t%s\t%s\n' "$ev" "$exists" "$writable" "$enabled" "$reason" >> "$CAPS"
  if (( ! enabled )); then
    state=EXECUTION_FAILED
    if (( ! exists )); then state=UNSUPPORTED
    elif (( ! writable )); then state=PERMISSION_DENIED
    fi
    hb_note_gap "$state" "$ev" "$reason"
  fi
done
if (( MINIMAL )); then
  exists=0; writable=0
  [[ -f "$TRACE_DIR/events/power/cpu_frequency/enable" ]] && exists=1
  [[ -w "$TRACE_DIR/events/power/cpu_frequency/enable" ]] && writable=1
  printf 'power/cpu_frequency\t%s\t%s\t0\t0\tnot_requested_minimal\n' "$exists" "$writable" >> "$CAPS"
fi
[[ -z "$ENABLED_EVENTS" ]] && { record_trace_status UNSUPPORTED no_trace_events_enabled; err "没有任何可用事件, 无法采集"; cleanup; exit 1; }
ok "已启用事件:$ENABLED_EVENTS"
print_banner

# sched_stat_wait 仅探测，不默认开启（依赖内核schedstats配置，避免额外高频事件）。
exists=0; writable=0
[[ -f "$TRACE_DIR/events/sched/sched_stat_wait/enable" ]] && exists=1
[[ -w "$TRACE_DIR/events/sched/sched_stat_wait/enable" ]] && writable=1
printf 'sched/sched_stat_wait\t%s\t%s\t0\t0\tnot_requested_overhead_budget\n' "$exists" "$writable" >> "$CAPS"
# ---------- 系统快照 ----------

snap_file(){ [[ -e "$SNAP/$2" ]] && return 0; [[ -r "$1" ]] && cp "$1" "$SNAP/$2" 2>/dev/null || echo "N/A (文件不存在)" > "$SNAP/$2"; }
phase_begin "采集系统静态快照 (/proc, /sys)"
: > "$SNAP/hostbound/export_errors.txt"
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

# 频率轮询复用内嵌 awk；能力缺失写入 manifest。
# ---------- 执行采集 ----------
START_TS=$(date +%s); START_TIME=$(date "+%Y-%m-%d %H:%M:%S")
echo "$START_TIME" > "$SNAP/trace_start_time.txt"
phase_begin "ftrace 采集 (${DURATION}s · $([[ $MINIMAL -eq 1 ]] && echo 精简 || echo 全量)模式$([[ -n "$PID_LIST" ]] && echo " · HostBound:$PID_LIST"))"
echo 1 > "$TRACE_DIR/tracing_on" || { record_trace_status PERMISSION_DENIED tracing_start_failed; err "开启 tracing 失败"; cleanup; exit 1; }
hb_poll & FREQ_PID=$!
echo 'CPU_HOST_WINDOW_START' > "$TRACE_DIR/trace_marker"
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
echo 'CPU_HOST_WINDOW_END' > "$TRACE_DIR/trace_marker"
echo 0 > "$TRACE_DIR/tracing_on"
if [[ -n "$FREQ_PID" ]]; then
  touch "$SNAP/hostbound/poll.stop"
  wait "$FREQ_PID" || echo "frequency_poll_failed" >> "$SNAP/hostbound/helper_error.txt"; FREQ_PID=""
fi
hb_phase end
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
        wait "$pid" 2>/dev/null || printf 'cpu%s export_failed\n' "${RUNNING[$pid]}" >> "$SNAP/hostbound/export_errors.txt"; unset "RUNNING[$pid]"; DONE=$((DONE+1))
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
  cat "$TRACE_DIR/trace" > "$SNAP/trace.txt" 2>/dev/null || echo "global_export_failed" >> "$SNAP/hostbound/export_errors.txt"
  spin_stop
  phase_end "已导出全局 trace 缓冲区 ($(fmt_bytes "$(stat -c %s "$SNAP/trace.txt" 2>/dev/null || echo 0)"))"
fi
shopt -u nullglob
[[ -s "$SNAP/trace.txt" ]] || { err "trace 为空, 事件可能未产生或 buffer 溢出"; }
# 记录 buffer 溢出情况 (注意: glob 不能加引号, 否则不展开)
# stats 是文件而不是 stats/overrun；无 bc 依赖，记录每核丢失证据。
mkdir -p "$SNAP/hostbound/trace_stats"
for f in "$TRACE_DIR"/per_cpu/cpu*/stats; do
  [[ -f "$f" ]] || continue
  c="${f%/stats}"; c="${c##*/}"
  cp "$f" "$SNAP/hostbound/trace_stats/$c.txt"
done
awk -F': *' '$1 ~ /^(overrun|commit overrun|dropped events)$/ && $2 ~ /^[0-9]+$/ {s+=$2;found=1} END {if(found)printf "%.0f\n",s}' \
  "$SNAP"/hostbound/trace_stats/cpu*.txt > "$SNAP/trace_overrun.txt" 2>/dev/null
printf '%s\n' "${CPU_LIST:-$(cat "$HB_SYS/devices/system/cpu/online")}" > "$SNAP/hostbound/collection_cpus.txt"

cleanup

# Bash/awk 证据和已生成的原生 Dump 随同归档。
record_trace_status COLLECTED

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
trace_clock: $TRACE_CLOCK
buffer_size_requested_kb: $BUFFER_SIZE
buffer_size_effective_kb: $BUFFER_EFFECTIVE
frequency_trace_unit: kHz
frequency_interval_sec: $FREQ_INTERVAL
process_discovery: $DISCOVER
nproc: $(nproc 2>/dev/null)
kernel: $(uname -r 2>/dev/null)
hostname: $(hostname 2>/dev/null)
trace_dir: $TRACE_DIR
EOF
phase_begin "打包采集包 (tar.gz 压缩)"
PKG=$(realpath "$OUTDIR" 2>/dev/null || echo "$OUTDIR")/${CAPTURE_NAME}.tar.gz
spin_start "压缩打包中, 数据量大时需要数分钟"
if tar -czf "$PKG" -C "$OUTDIR" "$CAPTURE_NAME" 2>/dev/null; then
  spin_stop
  PKG_SIZE=$(stat -c %s "$PKG" 2>/dev/null || echo 0)
  phase_end "打包完成"
  echo
  echo -e "${C_G}┌──────────────────────────────────────────────────────────────"
  echo -e "│ ${C_B}✔ 采集完成!${C_RST}${C_G} 总耗时 $(fmt_secs "$SECONDS")"
  echo -e "│${C_RST} 采集包: ${C_B}$PKG${C_RST} ${C_DIM}($(fmt_bytes "$PKG_SIZE"))${C_RST}"
  echo -e "${C_DIM}│ 提示: 可直接用本 Skill 分析, 或拖入 https://ui.perfetto.dev 查看${C_RST}"
  echo -e "${C_G}└──────────────────────────────────────────────────────────────${C_RST}"
  if [[ -s "$SNAP/hostbound/environment/msprechecker_dumped.json" ]]; then
    ok "包内 Ascend Dump: $CAPTURE_NAME/hostbound/environment/msprechecker_dumped.json"
  fi
else
  spin_stop
  warn "打包失败, 原始数据保留在: $SNAP/"
  ok "请将整个 cpu_trace 目录回传用于分析"
fi
exit 0
