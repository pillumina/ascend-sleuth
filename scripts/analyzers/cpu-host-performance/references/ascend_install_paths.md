# 昇腾软件安装路径与版本文件

供 CPU Host 采集器定位 Toolkit、Runtime、HCCL、驱动、ATB 与 MindIE 的版本文件。安装路径按现场安装方式与安装用户不同，页内路径只是默认入口；最终以采集进程实际读到的文件为准。

## 产品与算子包

| 产品 | Conda 的 ops 包名 |
|---|---|
| Atlas A2 训练 / 推理系列（下行产品单列） | `cann-910b-ops` |
| Atlas 200I/500 A2 推理产品 | `cann-310b-ops` |
| Atlas A3 系列 | `cann-a3-ops` |
| Ascend 950PR / 950DT（Ascend RecSDK 中标作 A5） | `cann-950-ops` |

表中采用 CANN 9.2.0-beta.2 的 Conda 包名。安装时 Toolkit 与对应芯片的 ops 通常装在同一路径；多芯片各自装 Toolkit 时可分目录。软件包清单与安装方式以现场版本的官方安装指南为准。

- [CANN 9.2.0-beta.2 软件安装指南](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/920beta2/softwareinst/instg/instg_0093.html)
- [Ascend RecSDK 芯片标识](https://github.com/Ascend/RecSDK/blob/develop/docker/OVERVIEW.zh.md#镜像-tag-中关键字段描述)

## 定位安装目录

| 安装方式 | 从哪里找 |
|---|---|
| 系统或个人 run 包 | root 默认前缀为 `/usr/local/Ascend`，普通用户为安装用户的 `$HOME/Ascend`。自定义安装时，CANN 的 `Install_Path` 见 `/etc/Ascend/ascend_cann_install.info` 或安装用户的 `$HOME/Ascend/ascend_cann_install.info`。 |
| 版本入口 | CANN 8.2 文档使用前缀下的 `ascend-toolkit/latest`；8.5 文档使用 `cann`；9.1 也提供 `cann-<version>` 的示例。装了多个版本时，以所选环境或安装记录为依据。 |
| Conda 环境 | Conda 安装的 Toolkit 和 NNAL 可位于当前环境的 `Ascend/` 内，示例入口为 `/home/miniconda3/Ascend/cann`。 |
| pip 环境 | 华为云镜像把 CANN 8.5 安装在 `<环境>/lib/python3.9/site-packages/ascend/cann-8.5.0`，并用 `ASCEND_HOME_PATH` 和 `ASCEND_TOOLKIT_HOME` 指向该目录。实际路径取决于 Python 环境和所装版本。 |

旧版运行环境还有 `<前缀>/nnrt/latest` 与 `<前缀>/nnae/latest` 两个独立入口。采集器只在这些入口下确实找到对应组件的版本文件时才记录该组件的版本。

- [CANN 8.2 安装指南 §10.2](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/82RC1alpha001/softwareinst/instg/CANN%E7%A4%BE%E5%8C%BA%E7%89%88%208.2.RC1.alpha001%20%E8%BD%AF%E4%BB%B6%E5%AE%89%E8%A3%85%E6%8C%87%E5%8D%97%2001.pdf)
- [CANN 8.5 路径表](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/850/softwareinst/instg/instg_0044.html)
- [CANN 9.1 版本查询](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/910/softwareinst/instg/instg_0064.html)
- [Conda 安装说明](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/920beta2/softwareinst/instg/instg_0093.html)
- [华为云 ModelArts 镜像示例](https://support.huaweicloud.com/intl/en-us/docker-modelarts/modelarts_23_0220.html)
- [旧版运行环境入口说明](https://www.hiascend.com/doc_center/source/en/canncommercial/601/inferapplicationdev/aclcppdevg/aclcppdevg_01_0004.html)

## 每个文件能证明什么

| 对象 | 版本证据和适用范围 |
|---|---|
| Toolkit 组合包 | 在选中的 CANN 目录下，`<arch>-linux/ascend_toolkit_install.info` 记录组合包版本、主机 CPU 架构和安装位置；`<arch>` 常见为 `aarch64` 或 `x86_64`。同目录的 `install.conf` 是安装参数，不是版本证据。 |
| Runtime、HCCL 等组件 | CANN 定义的包名对应 `<CANN目录>/share/info/<包名>`，各包以自己的 `version.info` 为准。HCCL 支持独立升级。ASC DevKit 是 Toolkit 的子包，其版本文件只证明这个子包。 |
| 驱动 | `/etc/ascend_install.info` 的 `Driver_Install_Path_Param` 给出驱动安装前缀，默认版本文件为 `/usr/local/Ascend/driver/version.info`。容器挂载会改变文件可见性。 |
| ATB | NNAL 安装指南给出的 ATB 版本证据是 `<安装前缀>/nnal/atb/latest/version.info`。NNAL 为可选加速库。 |
| MindIE | 官方镜像以 `<安装前缀>/mindie/latest/version.info` 展示套件及各组件版本；`mindie/latest/mindie-service/version.info` 记录 Service 组件的版本。 |
| OPP | OPP 可由 `ASCEND_OPP_PATH/version.info` 单独定位；整包安装记录是 `<arch>-linux/ascend_ops_install.info`，不要用它替代算子库自身的版本文件。 |

- [CANN 8.5 安装记录](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/850/softwareinst/instg/instg_0044.html)
- [CANN 版本接口](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/API/runtimeapi/aclcppdevg_03_2096.html)
- [驱动路径配置](https://www.hiascend.com/doc_center/source/en/canncommercial/850/maintenref/troubleshooting/troubleshooting_0221.html)
- [ATB / NNAL 安装说明](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/920beta2/softwareinst/instg/instg_0093.html)
- [MindIE 官方镜像说明](https://gitee.com/ascend/ascend-docker-image/blob/dev/mindie/README.md)

## 现场核对

`ASCEND_HOME_PATH` 和 `ASCEND_TOOLKIT_HOME` 表示 Toolkit 安装后的目录，`ASCEND_OPP_PATH` 单独指向算子库根目录。这三个变量属于当前进程环境；sudo 启动的采集进程可能拿到不同的值，容器也会改变可见范围。先用运行用户环境确认当前 Toolkit 目录，再按下面的命令列出实际存在的版本文件：

```bash
cann_dir=/usr/local/Ascend/cann
for file in "$cann_dir"/*/version.info "$cann_dir"/share/info/*/version.info \
    "$cann_dir/$(uname -m)-linux/ascend_toolkit_install.info"; do
  [[ -f "$file" ]] && printf '%s\n' "$file"
done
```

把实际路径、包名、文件中的版本字段与 Manifest 的 `source` 一起核对。版本目录名与组件版本值可以不同：曾见 `/usr/local/Ascend/cann` 链接到 `cann-9.0.0`，而 `share/info/{runtime,hccl,asc-devkit}/version.info` 三份文件都写 `Version=9.2.0`。同机多套安装时逐套核对，不要用一个目录的版本代表全部。

- [华为环境变量说明](https://www.hiascend.com/doc_center/source/zh/CANNCommunityEdition/910/maintenref/envvar/envref_07_0003.html)
- [整包版本查询](https://www.hiascend.com/doc_center/source/zh/canncommercial/850/softwareinst/instg/instg_0064.html)

本页按上游 `cpu-host-performance/references/ascend_install_paths.md` 整理，上游固定提交见 `scripts/analyzers/PROVENANCE.yaml`。
