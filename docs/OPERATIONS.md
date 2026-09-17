# 日常操作：OJO Community Opportunity Agent

当前只有模拟数据可用。此页描述获得 Reddit 对 OJO 商业监测的书面许可后，如何启动真实工作流；设置 `APPROVED=true` 只是操作开关，**不是许可本身**。飞书目标是普通电子表格，不是多维表格。

## 现在就能准备

1. 打开[演示页](https://reddit-opportunity-agent.vercel.app/)，下载“飞书审核表模板”和“社区规则清单”。模板全部是虚构数据，不能当成真实机会。
2. 在飞书建立一份仅限运营人员访问的**普通电子表格**。新建一个空白工作表作为自动审核队列。同步程序只管理这个工作表的 `A1:AP10`；不要放其他数据或公式在这个范围。另建工作表导入规则清单，逐社区人工记录自推广、链接、账号年龄、karma、问卷、产品反馈和每周推广帖要求。未知一律记 `unknown`。
3. 在 [Reddit 官方申请入口](https://support.reddithelp.com/hc/en-us/requests/new?tf_42139884615700=api_request_type_enterprise_clone&ticket_form_id=14868593862164)申请 OJO 商业用途的只读 API 权限。参考[申请范围草稿](REDDIT_ACCESS_REQUEST.md)，把 Feishu 存储/共享、DeepSeek 处理、保留期限和目标社区讲清楚。不要在批准前抓取或导入真实帖子。

## 获批后的配置

在 GitHub repository 的 Actions Variables/Secrets 中设置；不要放进代码、公开 Issue 或聊天：

| 类别 | 变量或密钥 | 用途 |
| --- | --- | --- |
| Variable | `REDDIT_APPROVAL_CONFIRMED=true` | 仅在拿到对应书面许可后开启 |
| Secret | `REDDIT_APPROVAL_REFERENCE` | 可核对的书面许可编号/描述 |
| Variable | `REDDIT_TARGET_SUBREDDITS` | **许可覆盖的**社区，逗号分隔；每日任务要求显式设置 |
| Secrets | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | 获批的 OAuth app；User-Agent 如实标明应用和运营账号 |
| Secret | `REPORT_ENCRYPTION_KEY` | 足够长的随机短语，仅用于加密每日原始报告 |
| Secrets | `OJO_VERIFIED_FACTS_JSON`, `REDDIT_PROMOTION_POLICIES_JSON` | 可选：核实的卖点及经人工核查的社区政策。没有就不提产品 |
| Variable + secret | `REDDIT_FEISHU_SHARING_APPROVED=true`, `REDDIT_FEISHU_APPROVAL_REFERENCE` | Reddit 书面许可明确允许飞书存储/共享后才启用同步 |
| Variable | `FEISHU_RETENTION_CLEANUP_ENABLED=true` | 飞书队列一旦产生真实数据就保持开启；独立于 Reddit 抓取清理到期行 |
| Secrets | `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_SPREADSHEET_TOKEN`, `FEISHU_SHEET_ID` | 飞书自建应用及指定普通电子表格/工作表 |
| Variable + secrets | `REDDIT_AI_PROCESSING_APPROVED=true`, `REDDIT_AI_APPROVAL_REFERENCE`, `DEEPSEEK_API_KEY` | 仅许可明确允许 DeepSeek 第三方处理时启用 |

飞书应用需要能读写所选电子表格。按[官方 Sheets 接口](https://www.postman.com/feishu-op/feishu-s-public-workspace/request/qo96yqv/)为应用授予相应权限，并给应用访问目标文档的权限。电子表格 token 和工作表 ID 从你自己创建的表格取得；两者不要公开。程序不会创建表格、改共享权限或触碰多维表格。首次同步必须是空白 `A1:AP10` 或完全匹配模板表头；陌生布局会拒绝写入。

本地真实运行也必须设置同样的 Reddit 许可与 OAuth 环境变量。复制 `config.example.json` 到被 Git 忽略的 `config.local.json`，只保留许可覆盖的社区，填入经核实的 OJO 产品事实。要允许建议自然提 OJO，需记录具体社区规则页面、30 天内核查时间和必需的账号门槛；没有证据就只提供非推广建议。`config.example.json` 中的 12 个社区只是初始研究名单，不能当作许可名单。

## 每天 09:17（北京时间）

GitHub Actions 的 `Daily opportunity list` 在北京时间 09:17 扫描，在 21:17 只执行保留期清理：许可缺失时跳过扫描；获批后只读筛选最多 3 条、先上传仅保留 1 天的加密报告；若另有飞书共享许可，再同步普通表格。同步失败会显示为失败，不会默默宣称已交付。可以在 Actions 手动运行 **synthetic_demo** 检查流程，不调用 Reddit、飞书或 DeepSeek。

本地获批运行：

```bash
python -m reddit_opportunity_agent.cli live --config config.local.json
python -m reddit_opportunity_agent.cli sync-feishu --input path/to/feishu_review.csv
```

`--ai` 仅在书面许可明确包括向 DeepSeek 发送选中帖子标题和至多 1,200 字正文时添加；否则不要用。若有经许可的导出文件，可用 `import --input approved-posts.json --config config.local.json`，不能把导出当成规避许可的办法。

每日人工审核：打开原帖、确认仍存在且主题没变；复核当前社区规则、账号条件、产品事实；选择“跳过 / 仅贡献观点 / 可自然提 OJO 并披露关系”，修改草稿，然后**人手动发布**。普通表格把 Review Status / Original Thread Read / Rules Checked / Product Claims Checked / Affiliation Disclosed / Manual Reply URL 等审核栏放在左侧，便于逐条处理。P0 只是高匹配建议，不代表版规许可。P1 不提产品，P2 不参与讨论。

若想把需求信号带入周报，先把 Review Status 设为已审核/已批准/已回复/已跳过，再在 Query Candidate、Question Theme、Use Case Insight、Competitor Pain、Product Feedback、Content Idea 填写**自己概括的短标签**，并把 Generalized Attested 设为 `Yes`。不要复制原帖句子、用户名、URL 或草稿。待审核或未确认的文本不得进入长期 digest；只是想记录私有临时备注时使用 Reviewer Notes，系统不会把备注导入周报。

## 留存与周复盘

飞书队列最多 9 行，保留审核者修改过的内容；若满额会报错而不会静默丢掉新机会。每行设为生成后 24 小时到期，北京时间 09:17 和 21:17 都尝试清理（需保持 `FEISHU_RETENTION_CLEANUP_ENABLED=true` 和飞书凭据有效）；这只是定时任务，不是绝对删除保证。若连接/清理失败、GitHub 调度延迟或授权撤销，表格负责人必须手动清掉到期内容。若书面许可要求更短，应先调整程序/调度再启动。若 Reddit 内容被删除、作者撤回或需移除，应尽快从飞书和本地报告删去对应内容。不要把真实内容上传到公开 Vercel 页面。

每日输出的 `daily_digest.json` 只保留受控类别和数字，不含帖子 ID、链接、标题、原问题或草稿。

在飞书机会行到期清理前，从飞书导出已审核的工作表 CSV，生成纳入“已回复/实测互动”及**已人工确认概括**的需求标签的更新版 digest；同时原始报告必须仍在其 48 小时处理窗口内。该导入只接受与当日原始报告匹配的行，不会把原帖、草稿或自由备注带入长期文件：

```bash
python -m reddit_opportunity_agent.cli digest \
  --input path/to/opportunities.json \
  --reviews path/to/feishu-export.csv
```

把每天最终版 `daily_digest.json` 复制到一个**仅含 digest JSON** 的本地目录（不要把原始 `opportunities.json` 混进去），再运行：

```bash
python -m reddit_opportunity_agent.cli weekly --input path/to/daily-digests
```

生成的 `weekly.md`/`weekly.json` 区分“未测量”和“0”，并提醒每日选中数可能跨天重复。人工归纳的 query、产品反馈与竞品问题需在原始内容仍在合法保留期内处理，不能直接把原帖复制成长期保存的洞察。实际评论互动、自然提及、Reddit referral、注册、激活与付费只能来自人工记录或自己的分析系统，Agent 不会凭帖子分数推断转化。

加密报告下载后可在本地解密；不要把解密文件提交到 Git：

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in opportunities.tar.gz.enc -out opportunities.tar.gz \
  -pass env:REPORT_ENCRYPTION_KEY
tar -xzf opportunities.tar.gz
```

## 故障边界

- 真实抓取被跳过：检查书面许可、`REDDIT_APPROVAL_CONFIRMED`、reference、目标社区与 OAuth 凭据；不要改用匿名接口或 RSS。
- 飞书不同步：先确认独立共享许可；再确认自建应用有表格权限、指定工作表存在、`A1:AP10` 是空白或预期表头。程序会拒绝覆盖陌生数据；满额时查看加密报告并人工处理队列。
- 社区规则未知/过期：不提产品、不贴链接；由人工先核查。不能用模型输出当规则证据。
- DeepSeek 不可用：保持确定性草稿，人照常审核；AI 不影响优先级或许可判断。
