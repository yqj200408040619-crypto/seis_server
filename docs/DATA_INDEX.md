# 数据及排除项索引

源码归档使用原始包内字节。未提交的大数据/缓存/运行环境逐项列在 [CODE_PROVENANCE.csv](CODE_PROVENANCE.csv)，包括源包、原路径、大小及原始 SHA-256。源包身份见 [SOURCE_ARCHIVES.json](SOURCE_ARCHIVES.json)，其中的 library_file_id 标识原始资料；运行时须从同一原包恢复所需输入至对应项目相对路径，并验证哈希。

排除原因计数：

{
  "rebuildable_environment_or_cache": 986,
  "outside_selected_application_tree": 48
}

原始包不重复提交为 zip/tar；原包和源文件 SHA-256 分别记录。生产数据库、原始波形不写入 Git。小型测试/模型输入和第三方源码/许可按用途保留，不按扩展名全部排除。原有仓库已跟踪的数据不删除。
