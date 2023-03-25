import glob
import os
import xlwings as xw
import logging
from excelexporter.generators import registers
from excelexporter.config import Configuration
from excelexporter.generator import Converter, Generator, CompletedHook
from excelexporter.sheetdata import SheetData, TypeDefine
from typing import Dict, Optional

# 导表工具引擎

logger = logging.getLogger(__name__)


class IllegalFile(Exception):

    def __init__(self, filename: str, *args: object) -> None:
        super().__init__(f"{filename} 不是配置表目录下的配置", *args)


class IllegalGenerator(Exception):
    def __init__(self, name: str, *args: object) -> None:
        super().__init__(
            name,
            *args
        )


class Engine(xw.App):

    def __init__(self, config: Configuration) -> None:
        super().__init__(visible=False)
        self.config = config
        self.generator: Optional[Generator] = None
        self.completed_hook: Optional[CompletedHook] = None
        self.extension: str = ""

        self.cvt = Converter()

        self.init_generator()

    def init_generator(self):

        generator = None
        completed_hook = None
        extension = None

        # 如果有自定义导出器就优先用自定义导出器
        if self.config.custom_generator.endswith(".py"):
            with open(self.config.custom_generator) as f:
                code = f.read()
                exec(code)
                self.generator = generator
                self.completed_hook = completed_hook
                self.extension = extension

                if (generator and completed_hook and extension) is False:
                    raise IllegalGenerator(
                        self.config.custom_generator,
                        "自定义导出器不完整，generator、completed_hook、extension存在没定义。")

                logger.info(f"使用 {self.config.custom_generator} 自定义导出器")
        else:
            # 没有才用内置的
            module = registers.get(
                self.config.custom_generator.upper()
            )
            if module is None:
                raise IllegalGenerator(
                    self.config.custom_generator, "不是内置导出器，请检查配置。")
            logger.info(
                f"使用内置导出器 {self.config.custom_generator} :{module.__name__}")
            self.generator = getattr(module, "generator")
            self.completed_hook = getattr(module, "completed_hook")
            self.extension = getattr(module, "extension")

    def _gen(self, excel_file: str):
        wb_abs_path: str = os.path.abspath(excel_file)
        abs_input_path: str = os.path.abspath(self.config.input)
        abs_output_path: str = os.path.abspath(self.config.output)
        wb_abs_path_without_ext: str = os.path.splitext(wb_abs_path)[0]

        if not wb_abs_path.startswith(abs_input_path):
            raise IllegalFile(wb_abs_path, abs_input_path)

        sheet_datas = self._excel2dict(wb_abs_path)

        for sheet_name, sheetdata in sheet_datas.items():
            try:
                if "-" in sheet_name:
                    org_name, rename = sheet_name.split("-")
                else:
                    org_name, rename = sheet_name, None

                relative_path = os.path.join(
                    wb_abs_path_without_ext.replace(abs_input_path, ""),
                    rename or org_name
                )
                output = abs_output_path + relative_path

                output_dirname = os.path.dirname(output)
                # 保持输出的文件目录层级结构与输入一致
                if not os.path.exists(output_dirname):
                    os.makedirs(output_dirname)

                code = self.generator(sheetdata, self.config)

                # code = "# 本文件由代码生成，不要手动修改\n"+code
                output = f"{output}.{self.extension}"
                with open(output, "w", encoding="utf-8", newline="\n") as f:
                    f.write(code)
                    logger.info(f"导出：{wb_abs_path}:{sheet_name} => {output}")
            except Exception:
                logger.error(f"{sheet_name} 导出失败", exc_info=True)

    def _excel2dict(self, wb_file: str) -> Dict[str, SheetData]:
        """
        workbook解析加工成字典
        """
        with self.books.open(wb_file) as book:
            ignore_sheet_mark = self.config.ignore_sheet_mark
            # 过滤掉打了忽略标志的sheet
            sheets = filter(
                lambda sheet: not sheet.name.startswith(ignore_sheet_mark),
                book.sheets
            )

            wb_data = {}

            # 先讲sheet转sheet_data
            for sheet in sheets:
                sheet_data = SheetData()
                row_values = sheet.range("A1").expand().raw_value

                sheet_data.define.type = list(row_values[0])
                sheet_data.define.desc = list(row_values[1])
                sheet_data.define.name = list(row_values[2])

                sheet_data.table = list([list(row) for row in row_values[3:]])
                # 找出所有被打了忽略标记的字段
                for col, field in enumerate(sheet_data.define.name):
                    # 跳过没命令的字段
                    if field and field.startswith(self.config.ignore_field_mark):
                        del sheet_data.define.type[col]
                        del sheet_data.define.desc[col]
                        del sheet_data.define.name[col]
                        for row in sheet_data.table:
                            del row[col]

                wb_data[sheet.name] = sheet_data

            cvt = Converter()
            for sheet_name, sheet_data in wb_data.items():
                field_names = sheet_data.define.name
                field_types = sheet_data.define.type
                table = {}

                for row in sheet_data.table:
                    id_type = TypeDefine.from_str(field_types[0])
                    id_name = field_names[0]
                    id_value = row[0]
                    id = cvt(id_value, id_type, id_name, id_value)

                    row_data = {}

                    for index, value in enumerate(row):
                        field_name: str = field_names[index]
                        field_type = TypeDefine.from_str(field_types[index])
                        row_data[field_name] = cvt(
                            id.value, field_type, field_name, value)

                    table[id.value] = row_data
                wb_data[sheet_name] = table

            return wb_data

    def gen_one(self, filename: str):
        self._gen(filename)
        if self.completed_hook:
            self.completed_hook(self.config)

    def gen_all(self):
        abs_input = os.path.abspath(self.config.input)
        exts = [".xlsx", ".xls"]
        for ext in exts:
            full_paths = glob.glob(f"{abs_input}/**/*{ext}", recursive=True)
            for full_path in full_paths:
                filename = os.path.basename(full_path)
                if filename.startswith("~$"):
                    logger.warning(f"{filename} 不是配置表，跳过！")
                    continue
                self._gen(full_path)

        if self.completed_hook:
            self.completed_hook(self.config)
