# 脚本操作

需要 Python 3.10+，仅标准库，无 pip 依赖。使用宿主已有 Python，命令中的 `python3` 可替换为实际解释器。路径以 Skill 根目录为基准。没有 Python 时可用宿主文件/网络工具按同等规则完成，但必须明确持久化或比对能力限制，不伪造执行结果。

默认数据位置：macOS `~/Library/Application Support/whatnot-seller-insights`，Windows `%LOCALAPPDATA%/whatnot-seller-insights`，Linux `$XDG_DATA_HOME/whatnot-seller-insights`（默认 `~/.local/share`）。SQLite事务保存画像、各来源进度、快照和报告全文；报告另导出 Markdown。不是加密存储，不存账号秘密。临时画像、coverage 和报告草稿也放此私有目录，不放 Git 仓库。可通过全局参数 `--data-dir ABSOLUTE_PATH` 指定其他私人位置。

```sh
python3 scripts/intelligence.py profile
python3 scripts/intelligence.py profile --file /private/path/profile.json
python3 scripts/intelligence.py plan
python3 scripts/intelligence.py plan --start '2026-10-01T00:00:00+08:00' --end '2026-10-12T23:59:59+08:00'
python3 scripts/intelligence.py collect RUN_ID
python3 scripts/intelligence.py finish RUN_ID --coverage /private/path/coverage.json --report /private/path/draft.md
python3 scripts/intelligence.py history
python3 scripts/intelligence.py clear --scope records
```

`profile --file` 替换整份画像，先合并旧字段。示例：
```json
{"onboarding_done":true,"market":"US","language":"zh-CN","categories":[],"price_range":null,"shipping_origin":null,"stage":"已有店铺","challenge":null}
```
首次询问后即使跳过也保存 `onboarding_done:true`。不要把文档示例当真实用户资料。

`plan` 输出 run id 和各来源日期范围；不推进进度。`collect` 输出证据文件路径，读取其中候选及 previous 进行比较；抓取失败也会保存部分证据及错误，不推进进度。其余来源用宿主检索，并把实际覆盖写入报告。

完成后准备 coverage JSON，key 为来源组 ID，未查的组可省略：
```json
{
  "whatnot-help": {
    "status":"complete",
    "start":"2026-10-01T00:00:00+00:00",
    "end":"2026-10-12T00:00:00+00:00",
    "evidence":"公开 API 全部分页读取成功；逐项核实相关候选，具体链接及限制见报告"
  },
  "industry": {"status":"partial","evidence":"仅核实最近三天，较早归档未读到；见报告待查区间"}
}
```
日期必须使用该次真实计划和覆盖时间，不照抄示例。complete 可用于一个从原起点连续查完的子区间；未查完的尾段自动留待下一次。只能零散核查时标 partial，原进度不动，报告注明已查项目避免重复。显式历史查询可填补连续缺口但不会越过缺口。报告保存失败或未执行 finish 都不会推进进度。不要在报告未核查前 finish。

官方采集成功仅表示获取当前文章目录；需 Agent完成候选核查并披露历史限制，才可标 complete。部分采集不能标 complete。非官方来源完成与否由 Agent根据实际证据判断，脚本不替代该判断。首次缺少旧版本时将结果称为“时间窗内有编辑记录的当前信息”，不声称已验证所有政策差异。

`history` 列出报告 ID 和覆盖情况；同目录 `ID-report.md` 是完整报告。日常先看 history 的未完成范围和既有报告再补查，日期重叠时按来源 URL/事实去重。clear 的 scope 可选 profile、records、all，仅删除本工具管理的记录和导出文件，不处理用户另存副本或系统备份。用户明确要求清除时执行对应范围。
