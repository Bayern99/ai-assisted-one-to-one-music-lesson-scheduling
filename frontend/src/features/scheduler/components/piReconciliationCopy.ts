export type PiLocale = 'zh' | 'en'

const STORAGE_KEY = 'pi-reconciliation-locale'

export function readPiLocale(): PiLocale {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh'
  } catch {
    return 'zh'
  }
}

export function writePiLocale(locale: PiLocale): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    /* ponytail: private-mode storage can throw; locale still works for this session */
  }
}

type Copy = {
  panelAria: string
  panelTitle: string
  tagline: string
  privacy: string
  switchToEn: string
  switchToZh: string
  switchLabel: string
  expandReading: string
  backToGrid: string
  model: string
  thinking: string
  stale: string
  noResult: string
  elapsed: string
  statusReady: string
  statusChoice: string
  statusMissing: string
  statusNoPackage: string
  optionA: string
  optionB: string
  optionGeneric: string
  termReady: string
  termNoPackage: string
  termBudget: string
  termTimeout: string
  termCrash: string
  termInterrupted: string
  termError: string
  phaseQueued: string
  phasePreflight: string
  phaseInvestigating: string
  phaseSaving: string
  phaseCompleted: string
  phaseFailed: string
  validating: string
  inspecting: string
  pendingTradeoff: string
  pendingFact: string
  pendingException: string
  pendingDefault: string
  unplaced: string
  unplacedLesson: string
  withdrawn: string
  withdrawnSacrifice: string
  place: string
  withdraw: string
  move: string
  roomChange: string
  timeChange: string
  lessons: string
  teacherDayBlock: string
  inspect: string
  colTeacher: string
  colLesson: string
  colFrom: string
  colTo: string
  colNote: string
  stillUnplaced: string
  confirmTeachers: string
  confirmed: string
  sacrificeAuth: string
  authorizeSacrifice: string
  unverified: string
  priorNote: string
  compare: string
  selectOption: string
  optionChanges: string
  sameAsCommon: string
  lessonDetails: string
  commonHeading: string
  commonNote: string
  commonChanges: string
  applyCommon: string
  confirmHeading: string
  timeChangeNotice: string
  noConfirm: string
  continueHeading: string
  lastInstruction: string
  goalAria: string
  goalPlaceholder: string
  investigating: string
  reinvestigate: string
  coverage: string
  optionIds: string
  primarySim: string
  fallbackSim: string
  rationale: string
  tradeoffs: string
  limitations: string
  pendingOriginal: string
  evidence: string
  interruptedTitle: string
  interruptedTimeout: string
  interruptedBudget: string
  revisionHeading: string
  thisRound: string
  contextHeading: string
  accepts: string
  busy: string
  noBusy: string
  piLeans: string
  focusHow: string
  focusNone: string
  continueDecision: string
  continueStop: string
  continueApplied: string
  continueRejected: string
  noteAria: string
  notePlaceholder: string
  apply: string
  defer: string
  recordClose: string
  remainingHeading: string
  remainingAria: string
  pendingHeading: string
  appliedFocus: string
  appliedChanges: string
  appliedNote: string
  appliedDetails: string
  rejectedBody: string
  rejectedBodyNote: string
  rejectedFallback: string
  initialGuidance: string
  initialPlaceholder: string
  investigateDay: string
  metricsSim: string
  metricsValid: string
  metricsRejected: string
  metricsTools: string
  focusReady: string
  focusChoice: string
  focusMissing: string
  focusNoPackage: string
  effectProtect: string
  effectTimeChange: string
  effectEliminated: string
  effectCommonKept: string
  effectCommonChanged: string
  effectCommonLost: string
  effectContinued: string
  none: string
  days: [string, string, string, string, string, string, string]
}

export const COPY: Record<PiLocale, Copy> = {
  zh: {
    panelAria: 'PI 排课调查',
    panelTitle: 'PI 排课调查',
    tagline: '全天委托 · 固定时间 · 优先保留 · 仅沙箱验证',
    privacy: '一次调查覆盖当天的未排课程及其连带调整。Python 校验每个方案，Pi 无法修改课表。',
    switchToEn: 'Switch to English',
    switchToZh: '切换为中文',
    switchLabel: 'EN',
    expandReading: '展开阅读',
    backToGrid: '返回课表',
    model: 'Pi 模型',
    thinking: '思考强度',
    stale: '课表已发生变化，此建议已失效，请重新调查后再应用。',
    noResult: 'Pi 没有提交调查结果。',
    elapsed: '已用时 {n} 秒',
    statusReady: '可以直接执行',
    statusChoice: '需要你做业务选择',
    statusMissing: '缺少会改变结论的信息',
    statusNoPackage: '当前没有可行方案',
    optionA: '方案 A',
    optionB: '方案 B',
    optionGeneric: '方案 {id}',
    termReady: '调查完成',
    termNoPackage: '没有找到可行方案',
    termBudget: '调查中断 · 已达探索上限',
    termTimeout: '调查中断 · 超出运行时限',
    termCrash: '调查中断 · Pi 进程意外退出',
    termInterrupted: '调查中断',
    termError: '调查失败',
    phaseQueued: '排队等待执行',
    phasePreflight: '正在检查输入',
    phaseInvestigating: '正在调查当天的关联调整',
    phaseSaving: '正在保存调查结果',
    phaseCompleted: '调查完成',
    phaseFailed: '调查失败',
    validating: '正在验证方案',
    inspecting: '正在检查全天安排',
    pendingTradeoff: '业务取舍',
    pendingFact: '缺少事实',
    pendingException: '例外授权',
    pendingDefault: '需要你决定',
    unplaced: '未排',
    unplacedLesson: '未排课',
    withdrawn: '退回未排',
    withdrawnSacrifice: '退回未排课（牺牲）',
    place: '安置',
    withdraw: '撤回',
    move: '移动',
    roomChange: '换房间',
    timeChange: '改时间（例外）',
    lessons: '节',
    teacherDayBlock: '（教师日区块，共 {n} 节）',
    inspect: '查看详情',
    colTeacher: '老师',
    colLesson: '课程',
    colFrom: '从',
    colTo: '到',
    colNote: '说明',
    stillUnplaced: '仍未安排：',
    confirmTeachers: '应用前请确认已征得每位老师同意：',
    confirmed: '已征得 {name} 同意',
    sacrificeAuth: '以下已排课程将退回未排，需逐项授权：',
    authorizeSacrifice: '授权牺牲 {who}{when}',
    unverified: '⚠ 未核实：',
    priorNote: '上次调查：{goal}（结论：{termination}）',
    compare: '方案比较',
    selectOption: '选择{option}',
    optionChanges: '{option} 变更',
    sameAsCommon: '与共同部分相同；差别在仍未安排的课。',
    lessonDetails: '{option} 逐节明细（{n} 节）',
    commonHeading: '共同部分',
    commonNote: '两个方案都包含以下调整，只需执行一次：',
    commonChanges: '共同变更',
    applyCommon: '先执行共同部分',
    confirmHeading: '需要你确认',
    timeChangeNotice: '{option}包含同日改时例外，应用前必须征得以上每位老师同意。',
    noConfirm: '本方案无需额外确认，可以直接应用。',
    continueHeading: '继续沟通',
    lastInstruction: '上一次的指示:{goal}',
    goalAria: '给 Pi 的留言',
    goalPlaceholder: '告诉 Pi 新条件：不要动哪位老师、可以接受改时间、未排课怎么处理…',
    investigating: 'Pi 正在调查…',
    reinvestigate: '用这些条件重新调查',
    coverage: '覆盖 {inspected}/{total} 个科目',
    optionIds: '方案编号:',
    primarySim: '首选模拟:{id}',
    fallbackSim: ' · 备选模拟:{id}',
    rationale: '理由原文:',
    tradeoffs: '取舍:',
    limitations: '局限:',
    pendingOriginal: '待决定原文:',
    evidence: '调查过程',
    interruptedTitle: '调查中断 · 有可用方案',
    interruptedTimeout: '调查被运行时限截断。已验证的方案仍可应用；未覆盖的部分需要重新调查。',
    interruptedBudget: '调查在完整覆盖前达到内部上限。已验证的方案仍可应用；未覆盖的部分需要重新调查。',
    revisionHeading: '你的指示改变了比较',
    thisRound: '本轮指示：',
    contextHeading: '相关背景',
    accepts: '可排',
    busy: '占用：',
    noBusy: '调查时段内无占用',
    piLeans: 'Pi 的倾向:',
    focusHow: '如何安排当天剩余的课？',
    focusNone: '当天没有找到可行方案',
    continueDecision: '补充条件让 Pi 调整这个方案（例如不要动哪位老师、哪些课可以接受改时间、剩下的未排课怎么处理）。所有方案仍由 Python 严格校验。',
    continueStop: '给 Pi 指一个新方向（例如要保护的老师、改时例外，或具体哪节未排课）。所有方案仍由 Python 严格校验。',
    continueApplied: '让 Pi 继续调查剩余的未排课程。所有方案仍由 Python 严格校验。',
    continueRejected: '调整边界后重新调查（例如更换可接受的代价或保护条件）。',
    noteAria: '决策备注',
    notePlaceholder: '备注（可选，记入本次任务记录）',
    apply: '应用',
    defer: '暂不处理',
    recordClose: '记录并关闭',
    remainingHeading: '未排课程',
    remainingAria: '仍未安排',
    pendingHeading: '需要你决定',
    appliedFocus: '方案已应用到课表',
    appliedChanges: '已应用的调整',
    appliedNote: '本次应用可以整体撤销；不会自动暂存或定稿。',
    appliedDetails: '实际生效的逐节变更（{n} 节）',
    rejectedBody: '这个结论已记录为不采纳。课表保持不变；需要时可以调整边界后重新调查。',
    rejectedBodyNote: '这个结论已记录为不采纳：{note}。课表保持不变；需要时可以调整边界后重新调查。',
    rejectedFallback: '该结论已记录为不采纳',
    initialGuidance: '一次调查覆盖当天的未排课程及其连带调整。Pi 在沙箱中探索候选方案，所有约束由 Python 校验。',
    initialPlaceholder: '希望这次调查达成什么？（可选）',
    investigateDay: '调查{day}的关联调整',
    metricsSim: '{n} 次验证',
    metricsValid: '{n} 个可行方案',
    metricsRejected: '{n} 个被 Python 否决',
    metricsTools: '{n} 次工具调用',
    focusReady: '这个方案已经通过验证，可以直接执行。',
    focusChoice: '需要在两个可行方案之间做选择。',
    focusMissing: '还缺少可能改变结论的信息，暂不宜直接执行。',
    focusNoPackage: '当前没有可行的完整方案。',
    effectProtect: '已转为硬约束：保护 {names} 当天已有安排。',
    effectTimeChange: '已转为硬约束：允许 {names} 改时间。',
    effectEliminated: '新约束下可行方案从 {from} 个变为 {to} 个。',
    effectCommonKept: '共同部分仍然可行。',
    effectCommonChanged: '共同部分有变化，需要重新确认。',
    effectCommonLost: '此前的共同部分在新约束下不再成立。',
    effectContinued: '在同一条决定上继续调查；可行方案集合没有因新约束改变。',
    none: '无',
    days: ['周日', '周一', '周二', '周三', '周四', '周五', '周六'],
  },
  en: {
    panelAria: 'PI Reconciliation',
    panelTitle: 'PI Reconciliation',
    tagline: 'Whole day · fixed time · keep placed lessons · sandbox only',
    privacy: 'One investigation covers the day’s unplaced lessons and linked moves. Python validates every package; Pi cannot change the timetable.',
    switchToEn: 'Switch to English',
    switchToZh: '切换为中文',
    switchLabel: '中文',
    expandReading: 'Expand reading',
    backToGrid: 'Back to timetable',
    model: 'Pi model',
    thinking: 'Thinking',
    stale: 'The timetable changed, so this advice is stale. Investigate again before applying.',
    noResult: 'Pi did not submit an investigation result.',
    elapsed: '{n}s elapsed',
    statusReady: 'Ready to apply',
    statusChoice: 'A business choice is needed',
    statusMissing: 'Missing information that could change the conclusion',
    statusNoPackage: 'No feasible package',
    optionA: 'Option A',
    optionB: 'Option B',
    optionGeneric: 'Option {id}',
    termReady: 'Investigation complete',
    termNoPackage: 'No feasible package found',
    termBudget: 'Stopped · search budget reached',
    termTimeout: 'Stopped · runtime limit',
    termCrash: 'Stopped · Pi process exited',
    termInterrupted: 'Stopped',
    termError: 'Investigation failed',
    phaseQueued: 'Queued',
    phasePreflight: 'Checking input',
    phaseInvestigating: 'Investigating linked moves for the day',
    phaseSaving: 'Saving the investigation',
    phaseCompleted: 'Investigation complete',
    phaseFailed: 'Investigation failed',
    validating: 'Validating packages',
    inspecting: 'Inspecting the day',
    pendingTradeoff: 'Business trade-off',
    pendingFact: 'Missing fact',
    pendingException: 'Exception authorization',
    pendingDefault: 'Needs a decision',
    unplaced: 'Unplaced',
    unplacedLesson: 'Unplaced',
    withdrawn: 'Withdrawn',
    withdrawnSacrifice: 'Withdrawn (sacrifice)',
    place: 'Place',
    withdraw: 'Withdraw',
    move: 'Move',
    roomChange: 'Room change',
    timeChange: 'Time change (exception)',
    lessons: 'lessons',
    teacherDayBlock: ' (teacher-day block, {n} lessons)',
    inspect: 'Details',
    colTeacher: 'Teacher',
    colLesson: 'Lesson',
    colFrom: 'From',
    colTo: 'To',
    colNote: 'Note',
    stillUnplaced: 'Still unplaced:',
    confirmTeachers: 'Confirm each teacher has agreed before applying:',
    confirmed: '{name} has agreed',
    sacrificeAuth: 'These placed lessons will return to unplaced and need per-item authorization:',
    authorizeSacrifice: 'Authorize sacrifice {who}{when}',
    unverified: '⚠ Unverified: ',
    priorNote: 'Previous investigation: {goal} (outcome: {termination})',
    compare: 'Comparison',
    selectOption: 'Select {option}',
    optionChanges: '{option} changes',
    sameAsCommon: 'Same as the shared part; the difference is which lessons stay unplaced.',
    lessonDetails: '{option} lesson details ({n})',
    commonHeading: 'Shared part',
    commonNote: 'Both options include these moves. Apply them once:',
    commonChanges: 'Shared changes',
    applyCommon: 'Apply shared part first',
    confirmHeading: 'Confirm before applying',
    timeChangeNotice: '{option} includes a same-day time-change exception. Each listed teacher must agree before apply.',
    noConfirm: 'No extra confirmation. This option can be applied.',
    continueHeading: 'Continue',
    lastInstruction: 'Last instruction:{goal}',
    goalAria: 'Message to Pi',
    goalPlaceholder: 'New conditions: whose day to leave alone, who may change time, what to do with leftovers…',
    investigating: 'Pi is investigating…',
    reinvestigate: 'Investigate with these conditions',
    coverage: 'Covered {inspected}/{total} subjects',
    optionIds: 'Option ids:',
    primarySim: 'Primary simulation:{id}',
    fallbackSim: ' · Fallback:{id}',
    rationale: 'Rationale:',
    tradeoffs: 'Trade-offs:',
    limitations: 'Limits:',
    pendingOriginal: 'Pending decisions:',
    evidence: 'Investigation log',
    interruptedTitle: 'Stopped · usable options remain',
    interruptedTimeout: 'The run hit the time limit. Validated options can still be applied; uncovered work needs another investigation.',
    interruptedBudget: 'The run hit the internal search cap. Validated options can still be applied; uncovered work needs another investigation.',
    revisionHeading: 'This round’s instruction',
    thisRound: 'This round: ',
    contextHeading: 'Context',
    accepts: 'Accepts',
    busy: 'Busy: ',
    noBusy: 'Empty in the investigated window',
    piLeans: 'Pi leans toward:',
    focusHow: 'How should the remaining lessons that day be placed?',
    focusNone: 'No feasible package for that day',
    continueDecision: 'Add conditions so Pi can adjust this package (whose day to leave alone, who may change time, what to do with leftovers). Python still validates every package.',
    continueStop: 'Give Pi a new direction (teachers to protect, a time-change exception, or a specific unplaced lesson). Python still validates every package.',
    continueApplied: 'Ask Pi to keep investigating the remaining unplaced lessons. Python still validates every package.',
    continueRejected: 'Investigate again after changing the acceptable cost or protection.',
    noteAria: 'Decision note',
    notePlaceholder: 'Note (optional, stored with this task)',
    apply: 'Apply',
    defer: 'Defer',
    recordClose: 'Record and close',
    remainingHeading: 'Unplaced lessons',
    remainingAria: 'Still unplaced',
    pendingHeading: 'Needs a decision',
    appliedFocus: 'Package applied to the timetable',
    appliedChanges: 'Applied changes',
    appliedNote: 'This apply can be undone as a whole. It does not auto-stage or finalize.',
    appliedDetails: 'Applied lesson changes ({n})',
    rejectedBody: 'This conclusion was recorded as not adopted. The timetable is unchanged; investigate again after adjusting the bounds if needed.',
    rejectedBodyNote: 'This conclusion was recorded as not adopted: {note}. The timetable is unchanged; investigate again after adjusting the bounds if needed.',
    rejectedFallback: 'This conclusion was recorded as not adopted',
    initialGuidance: 'One investigation covers the day’s unplaced lessons and linked moves. Pi explores candidates in a sandbox; Python validates every constraint.',
    initialPlaceholder: 'What should this investigation achieve? (optional)',
    investigateDay: 'Investigate {day} linked moves',
    metricsSim: '{n} validations',
    metricsValid: '{n} feasible packages',
    metricsRejected: '{n} rejected by Python',
    metricsTools: '{n} tool calls',
    focusReady: 'This package passed validation and can be applied.',
    focusChoice: 'A choice is needed between two feasible packages.',
    focusMissing: 'Information that could change the conclusion is still missing.',
    focusNoPackage: 'There is no feasible complete package.',
    effectProtect: 'Hard constraint: keep existing placements for {names}.',
    effectTimeChange: 'Hard constraint: {names} may change time.',
    effectEliminated: 'Feasible options went from {from} to {to} under the new constraint.',
    effectCommonKept: 'The shared part is still feasible.',
    effectCommonChanged: 'The shared part changed and needs another look.',
    effectCommonLost: 'The previous shared part no longer holds under the new constraint.',
    effectContinued: 'Continuing the same decision; the feasible set did not change under the new constraint.',
    none: 'None',
    days: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
  },
}

const SERVER_LABELS: Record<string, string> = {
  仍未安排: 'Remaining',
  已有课移动: 'Existing lessons moved',
  时间变化: 'Time changes',
  牺牲: 'Sacrifices',
  硬冲突: 'Hard conflicts',
}

const KNOWN_QUESTIONS: Record<string, Exclude<keyof Copy, 'days'>> = {
  '如何安排当天剩余的课？': 'focusHow',
  '当天没有找到可行方案': 'focusNone',
  '该结论已记录为不采纳': 'rejectedFallback',
  '方案已应用到课表': 'appliedFocus',
  '这个方案已经通过验证，可以直接执行。': 'focusReady',
  '需要在两个可行方案之间做选择。': 'focusChoice',
  '还缺少可能改变结论的信息，暂不宜直接执行。': 'focusMissing',
  '当前没有可行的完整方案。': 'focusNoPackage',
}

export function fmt(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => String(vars[key] ?? ''))
}

export function localizeServerLabel(locale: PiLocale, label: string): string {
  if (locale === 'zh') return label
  return SERVER_LABELS[label] ?? label
}

export function localizeServerValue(locale: PiLocale, value: string): string {
  if (locale === 'zh') return value
  if (value === '无') return COPY.en.none
  if (value === '未排') return COPY.en.unplaced
  return value.replace(/(\d+)\s*节/g, '$1 lessons').replace(/(\d+)\s*项/g, '$1 items')
}

export function localizeFocusQuestion(locale: PiLocale, question: string, status: string): string {
  const copy = COPY[locale]
  const key = KNOWN_QUESTIONS[question]
  if (key) return copy[key]
  if (!question) {
    if (status === 'choice') return copy.focusChoice
    if (status === 'missing_info') return copy.focusMissing
    if (status === 'no_package') return copy.focusNoPackage
    if (status === 'ready') return copy.focusReady
    return copy.focusHow
  }
  return question
}

export function localizeRevisionEffect(
  locale: PiLocale,
  code: string,
  text: string,
  revision: { protect_teachers?: string[] | null; allow_time_change_teachers?: string[] | null },
): string {
  if (locale === 'zh') return text
  const copy = COPY.en
  const names = (list?: string[] | null) => (list ?? []).filter(Boolean).join(', ')
  if (code === 'protect_applied') return fmt(copy.effectProtect, { names: names(revision.protect_teachers) })
  if (code === 'time_change_applied') return fmt(copy.effectTimeChange, { names: names(revision.allow_time_change_teachers) })
  if (code === 'common_kept') return copy.effectCommonKept
  if (code === 'common_changed') return copy.effectCommonChanged
  if (code === 'common_lost') return copy.effectCommonLost
  if (code === 'continued') return copy.effectContinued
  if (code === 'option_eliminated') {
    const match = text.match(/从\s*(\d+)\s*个变为\s*(\d+)\s*个/)
    if (match) return fmt(copy.effectEliminated, { from: match[1], to: match[2] })
  }
  return text
}
