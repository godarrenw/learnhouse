/**
 * 作业工具 e2e 的造数与清理。
 *
 * 全部走 REST API 建，**不碰数据库**，所以对着任何一套实例都能跑：自己 boot 的
 * 干净实例，或者 `E2E_SKIP_BOOT=1` 指向的本地预发栈。每次跑都新建一门带随机后缀
 * 的课，跑完把整门课删掉，不会在共享的预发栈里留垃圾，也不依赖里面原有的数据。
 *
 * 造出来的东西：
 *  - 一门课 + 一个章节
 *  - 一个富文本内容页，正文够长（AI 出题要求 ≥40 字），并且**改过两次**，
 *    于是有 v1 / v2 两个历史版本可以 diff 和回滚
 *  - 一份带截止日期的作业（学期复用的摘要要有东西可显示）
 *  - 一份形成性随堂测（一道选择题），可选地让一个学生交一份卷，
 *    好让结果面板有真实的答对率
 */
import { API_URL, uniqueSuffix } from '../../../core/instance'
import { req } from '../../../core/client'
import type { Org } from '../../../core/client'
import { saveTaskSubmission, submitAssignment } from '../../assignments/api'

/** 内容页的正文。AI 出题会读它，所以要像一节真课，不能是 lorem。 */
function pageDoc(revision: string) {
  const paragraphs = [
    '数控机床由控制系统、伺服驱动系统和机械本体三大部分组成。' +
      '控制系统负责解释加工程序并产生指令，伺服驱动系统把指令变成运动，' +
      '机械本体承担实际的切削。',
    'CNC 的全称是 Computer Numerical Control，中文叫计算机数控。' +
      '与普通机床相比，数控机床的加工精度和一致性都更高，适合小批量多品种的生产。',
    revision,
  ]
  return {
    type: 'doc',
    content: paragraphs.map((text) => ({
      type: 'paragraph',
      content: [{ type: 'text', text }],
    })),
  }
}

export interface AssignFixture {
  org: Org
  courseId: number
  courseUuid: string
  chapterId: number
  pageActivityUuid: string
  pageName: string
  quizAssignmentUuid: string
  quizTitle: string
  dueAssignmentTitle: string
  /** 交了卷的学生 id，没造出学生时是 null。 */
  submittedStudentId: number | null
}

async function createCourse(token: string, orgId: number, name: string): Promise<any> {
  const fd = new FormData()
  fd.set('name', name)
  fd.set('description', 'Seeded by ext/assign E2E')
  fd.set('public', 'true')
  fd.set('about', 'Seeded by ext/assign E2E')
  fd.set('learnings', '[]')
  fd.set('tags', '')
  const res = await fetch(`${API_URL}/courses/?org_id=${orgId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  })
  const text = await res.text()
  if (!res.ok) throw new Error(`createCourse -> ${res.status}: ${text}`)
  return JSON.parse(text)
}

/**
 * 建一份自足的夹具。`studentToken` 给了就顺便交一份卷，没有就跳过
 * （本地预发库是邀请制，harness 新建学生会 403，这时结果面板只能看空态）。
 */
export async function seedAssignFixture(
  adminToken: string,
  org: Org,
  studentToken?: string,
  studentId?: number,
): Promise<AssignFixture> {
  const suffix = uniqueSuffix()
  const course = await createCourse(adminToken, org.id, `E2E 作业工具 ${suffix}`)

  const chapter = await req<any>('POST', '/chapters/', adminToken, {
    name: '第一章 数控基础',
    description: '',
    org_id: org.id,
    course_id: course.id,
  })

  // --- 内容页：建出来是 v1，改两次拿到 v2 / v3 ---
  const pageName = '1.1 什么是数控？'
  const page = await req<any>(
    'POST',
    `/activities/?coursechapter_id=${chapter.id}&org_id=${org.id}`,
    adminToken,
    {
      name: pageName,
      activity_type: 'TYPE_DYNAMIC',
      activity_sub_type: 'SUBTYPE_DYNAMIC_PAGE',
      chapter_id: chapter.id,
      content: pageDoc('第一稿：先讲清楚三大组成部分。'),
      details: {},
      published: true,
    },
  )
  // 每次带 content 的 PUT 都会把改之前的内容存成一个历史版本
  for (const revision of [
    '第二稿：补充一段数控与普通机床的对比。',
    '第三稿：把 CNC 的英文全称写全，方便学生查资料。',
  ]) {
    await req('PUT', `/activities/${page.activity_uuid}`, adminToken, {
      content: pageDoc(revision),
    })
  }

  // --- 一份带截止日期的作业：学期复用的摘要要有东西可显示 ---
  const dueAssignmentTitle = '第一次作业：数控机床结构'
  const dueActivity = await req<any>(
    'POST',
    `/activities/?coursechapter_id=${chapter.id}&org_id=${org.id}`,
    adminToken,
    {
      name: dueAssignmentTitle,
      activity_type: 'TYPE_ASSIGNMENT',
      activity_sub_type: 'SUBTYPE_ASSIGNMENT_ANY',
      chapter_id: chapter.id,
      published: true,
    },
  )
  await req<any>('POST', '/assignments/', adminToken, {
    title: dueAssignmentTitle,
    description: 'Seeded by ext/assign E2E',
    due_date: '2099-03-01',
    published: true,
    grading_type: 'NUMERIC',
    org_id: org.id,
    course_id: course.id,
    chapter_id: chapter.id,
    activity_id: dueActivity.id,
  })

  // --- 形成性随堂测：走作业工具自己的接口建，顺带把 quick-quiz 也验了 ---
  const quizTitle = '随堂测：数控基础'
  const quiz = await req<any>(
    'POST',
    `/ext/assign/courses/${course.course_uuid}/chapters/${chapter.id}/quick-quiz?org_id=${org.id}`,
    adminToken,
    {
      title: quizTitle,
      formative: true,
      publish: true,
      questions: [
        {
          kind: 'quiz',
          title: '单选',
          questions: [
            {
              text: 'CNC 里的 C 指的是什么？',
              options: [
                { text: '计算机', correct: true },
                { text: '控制', correct: false },
                { text: '切削', correct: false },
                { text: '坐标', correct: false },
              ],
            },
          ],
        },
      ],
    },
  )

  // --- 可选：让学生交一份卷，好让结果面板有真实答对率 ---
  let submittedStudentId: number | null = null
  if (studentToken && studentId) {
    const tasks = await req<any[]>(
      'GET',
      `/assignments/${quiz.assignment_uuid}/tasks`,
      adminToken,
    )
    const task = tasks[0]
    const question = task.contents.questions[0]
    // 故意全选对，结果面板应该显示 100%
    await saveTaskSubmission(studentToken, quiz.assignment_uuid, task.assignment_task_uuid, {
      submissions: question.options.map((o: any) => ({
        questionUUID: question.questionUUID,
        optionUUID: o.optionUUID,
        answer: !!o.assigned_right_answer,
      })),
    })
    await submitAssignment(studentToken, quiz.assignment_uuid)
    submittedStudentId = studentId
  }

  return {
    org,
    courseId: course.id,
    courseUuid: course.course_uuid,
    chapterId: chapter.id,
    pageActivityUuid: page.activity_uuid,
    pageName,
    quizAssignmentUuid: quiz.assignment_uuid,
    quizTitle,
    dueAssignmentTitle,
    submittedStudentId,
  }
}

/** 把整门课删掉，章节、活动、作业、题目都会跟着级联删。 */
export async function cleanupAssignFixture(
  adminToken: string,
  fixture: Pick<AssignFixture, 'courseUuid'> | null,
): Promise<void> {
  if (!fixture) return
  await req('DELETE', `/courses/${fixture.courseUuid}`, adminToken).catch(() => {
    /* 清理失败不该让整条用例红掉，最坏情况是预发栈里留一门 E2E 课 */
  })
}

/** 学期复用会新建一门课，用例跑完要按名字找出来删掉。 */
export async function deleteCoursesNamed(
  adminToken: string,
  orgSlug: string,
  predicate: (_name: string) => boolean,
): Promise<number> {
  const courses = await req<any[]>(
    'GET',
    `/courses/org_slug/${orgSlug}/page/1/limit/100?include_unpublished=true`,
    adminToken,
  ).catch(() => [])
  let removed = 0
  for (const c of courses ?? []) {
    if (predicate(c.name ?? '')) {
      await req('DELETE', `/courses/${c.course_uuid}`, adminToken).catch(() => {})
      removed += 1
    }
  }
  return removed
}
