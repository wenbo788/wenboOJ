/** 提交页 / 沉浸做题共用的语言选项与默认代码模板 */
export const LANGUAGES = [
  { value: 'cpp', label: 'C++ (g++, C++14)', editorLang: 'cpp' },
  { value: 'c', label: 'C (gcc)', editorLang: 'c' },
  { value: 'python3', label: 'Python 3', editorLang: 'python' },
]

export const DEFAULT_CODE: Record<string, string> = {
  cpp: '#include <iostream>\nusing namespace std;\n\nint main() {\n  \n  return 0;\n}\n',
  c: '#include <stdio.h>\n\nint main() {\n  \n  return 0;\n}\n',
  python3: '',
}
