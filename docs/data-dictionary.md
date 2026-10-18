# 样本字段 v1

`data/samples.jsonl` 一行一个JSON对象；当前为既有首批样本的公开摘要。新采样建议先写 `data/batches/<run_id>.jsonl`，由整合者去重后并入主库，不覆盖旧观察。观测更新另起记录并注明与原记录关系；价格变化不能抹掉旧时间。

初始导入保留旧ID（XY01、SM01、XHS-001、YW01等）；后续用 `BR-YYYYMMDD-机器代号-序号`，不得重新使用ID。机器代号无需暴露设备名或个人身份。去重键是平台+干净详情URL，重复访问不是重复商机。

|字段|填写要求|
|---|---|
|`schema_version`|固定1；变更字段时同步此文和检查工具|
|`id`|唯一；能与阶段记录和证据索引对应|
|`platform`, `url`, `title`|真实平台、干净公开详情URL、自写去身份标题|
|`observed_at`, `observed_date`|原观察ISO时间含时区；旧资料缺确切时刻时前者null，后者明确日期|
|`imported_at`|本条整理入库时间，不替代原观察时间|
|`acquisition`|当前导入为`legacy_browser_observation`；新现场用`browser_observation`，用户截图用`user_provided_capture`|
|`access`|`public_web`、`logged_in_public`、`unknown`；不猜登录状态|
|`review_status`|`checked_against_saved_text`、`awaiting_review`；新现场人工核过可用`checked_at_source`；均不代表成交已核|
|`publication`|公共样本固定`public_summary`；私有资料不要混入此库|
|`sampling`|搜索词`query`、排序`sort`、位置`position`；未知null；记录偏差|
|`direct_observations`|自写短句，页面声明要归因，不复制完整页面|
|`prices`|`amount`、`currency`、`unit`、`tier`；金额与对应规格/起订量绑定；面议不编数字|
|`metrics`|`label`、`value`、`scope`、`meaning`；时间、对象和原标签不明就说未知|
|`mechanism_hypotheses`|可反驳解释，不能混作观察事实|
|`unverified`|实付、需求时效、交付/授权等具体缺口|
|`anomalies`|`detail`、`why_it_matters`、`next_check`；每个异常只需三句，不强制有异常|
|`evidence`|`id`、`kind`、`availability`、`public_pointer`、`integrity_sha256`；不包含本机私有路径|
|`limitations`|截断、截图未核、登录/区域差异、指标口径、样本偏差等|

价格支持CNY、SGD等ISO币种；不强行换汇。`prices` 和 `metrics` 允许空数组。没有可靠金额或数量用空项，不用0占未知。一级指标的对象范围不清时不能变成具体SKU销量。

原始证据只在本机时，`availability=local_only`、`public_pointer=null`。`kind=saved_page_text` 表示保存页面文字，`kind=saved_observation_record` 只表示执行者的结构化记录，两者不能混称原文。`integrity_sha256` 对应本机原文件校验值，可核文件一致性，不能证明来源真实。引用公开裁剪时必须先去身份和权利审查，并记录仓库相对路径；不存在的附件不能写`public`。

新采样的完整过程记录在 [会话模板](../templates/session.md)，公开样本不承担所有操作日志。评论中若发现新的独立需求可记单独线索，但不能用一篇帖子的评论数扩充独立页面样本数。
