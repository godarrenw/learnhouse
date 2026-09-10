-- 学情工具 QA 用的演示数据。只在本地预发栈（learnhouse-local）上跑，不碰生产。
-- 内容：一个班级用户组（挂到课程 2）+ 三名学生 + 一份 100 分作业 + 两条提交 + 学习记录。
BEGIN;

INSERT INTO "user" (id, username, first_name, last_name, email, avatar_image, bio, details, profile,
                    password, user_uuid, email_verified, failed_login_attempts, is_superadmin,
                    creation_date, update_date)
VALUES
 (9001,'stu_zhang','张','小明','zhang.xm@example.local','','', '{}','{}','!seed', 'user_seed_9001', true, 0, false, '2026-09-01 02:00:00', '2026-09-01 02:00:00'),
 (9002,'stu_li','李','小红','li.xh@example.local','','', '{}','{}','!seed', 'user_seed_9002', true, 0, false, '2026-09-01 02:00:00', '2026-09-01 02:00:00'),
 (9003,'stu_wang','王','大力','wang.dl@example.local','','', '{}','{}','!seed', 'user_seed_9003', true, 0, false, '2026-09-01 02:00:00', '2026-09-01 02:00:00')
ON CONFLICT (id) DO NOTHING;

INSERT INTO userorganization (user_id, org_id, role_id, creation_date, update_date)
SELECT u.id, 1, 4, '2026-09-01 02:00:00', '2026-09-01 02:00:00'
FROM (VALUES (9001),(9002),(9003)) AS u(id)
WHERE NOT EXISTS (SELECT 1 FROM userorganization uo WHERE uo.user_id = u.id AND uo.org_id = 1);

INSERT INTO usergroup (id, name, description, org_id, usergroup_uuid, creation_date, update_date)
VALUES (9001,'2026 秋 智能制造 1 班','QA 演示班级', 1, 'usergroup_seed_9001','2026-09-01 02:00:00','2026-09-01 02:00:00')
ON CONFLICT (id) DO NOTHING;

INSERT INTO usergroupuser (usergroup_id, user_id, org_id, creation_date, update_date)
SELECT 9001, u.id, 1, '2026-09-01 02:00:00', '2026-09-01 02:00:00'
FROM (VALUES (9001),(9002),(9003)) AS u(id)
WHERE NOT EXISTS (SELECT 1 FROM usergroupuser g WHERE g.usergroup_id = 9001 AND g.user_id = u.id);

INSERT INTO usergroupresource (usergroup_id, resource_uuid, org_id, creation_date, update_date)
SELECT 9001, 'course_52dfa130-f9dd-4cb6-9bab-50cc096d0971', 1, '2026-09-01 02:00:00', '2026-09-01 02:00:00'
WHERE NOT EXISTS (SELECT 1 FROM usergroupresource r WHERE r.usergroup_id = 9001);

-- 一份 100 分作业（两道题各 50 分），挂在课程 2 的第一个活动上
INSERT INTO assignment (id, title, description, due_date, published, grading_type, ungraded,
                        org_id, course_id, chapter_id, activity_id, assignment_uuid,
                        creation_date, update_date)
VALUES (9001,'第一次作业：数字孪生案例分析','读完 1.1-1.3 后提交一份案例分析','2026-09-05', true,
        'NUMERIC', false, 1, 2, 4, 9, 'assignment_seed_9001','2026-09-01 02:00:00','2026-09-01 02:00:00')
ON CONFLICT (id) DO NOTHING;

INSERT INTO assignmenttask (id, title, description, hint, contents, max_grade_value, assignment_type,
                            assignment_id, org_id, course_id, chapter_id, activity_id,
                            assignment_task_uuid, creation_date, update_date)
VALUES
 (9001,'第 1 题：选一个案例','','', '{}', 50, 'QUIZ', 9001, 1, 2, 4, 9, 'task_seed_9001','2026-09-01 02:00:00','2026-09-01 02:00:00'),
 (9002,'第 2 题：分析收益与风险','','', '{}', 50, 'QUIZ', 9001, 1, 2, 4, 9, 'task_seed_9002','2026-09-01 02:00:00','2026-09-01 02:00:00')
ON CONFLICT (id) DO NOTHING;

-- 张小明按时交并批了 86 分；李小红过了截止日期才交、还没批；王大力没交
INSERT INTO assignmentusersubmission (id, submission_status, grade, overall_feedback, attempt_number,
                                      user_id, assignment_id, assignmentusersubmission_uuid,
                                      creation_date, update_date)
VALUES
 (9001,'GRADED', 86, '案例选得好，风险部分可以再具体些', 1, 9001, 9001, 'aus_seed_9001','2026-09-04 06:00:00','2026-09-06 03:00:00'),
 (9002,'SUBMITTED', 0, NULL, 1, 9002, 9001, 'aus_seed_9002','2026-09-07 15:00:00','2026-09-07 15:00:00')
ON CONFLICT (id) DO NOTHING;

-- 学习记录：张小明看完 6 个活动，李小红看完 2 个，王大力没进过课
INSERT INTO trail (id, org_id, user_id, trail_uuid, creation_date, update_date)
VALUES (9001,1,9001,'trail_seed_9001','2026-09-02 01:00:00','2026-09-08 09:00:00'),
       (9002,1,9002,'trail_seed_9002','2026-09-03 01:00:00','2026-09-07 09:00:00')
ON CONFLICT (id) DO NOTHING;

INSERT INTO trailrun (id, data, status, trail_id, course_id, org_id, user_id, creation_date, update_date)
VALUES (9001,'{}','STATUS_IN_PROGRESS',9001,2,1,9001,'2026-09-02 01:00:00','2026-09-08 09:00:00'),
       (9002,'{}','STATUS_IN_PROGRESS',9002,2,1,9002,'2026-09-03 01:00:00','2026-09-07 09:00:00')
ON CONFLICT (id) DO NOTHING;

INSERT INTO trailstep (id, complete, teacher_verified, grade, data, trailrun_id, trail_id,
                       activity_id, course_id, org_id, user_id, creation_date, update_date)
SELECT 9100 + row_number() OVER (ORDER BY ca."order"), true, false, '', '{}', 9001, 9001,
       ca.activity_id, 2, 1, 9001,
       '2026-09-02 01:0' || (row_number() OVER (ORDER BY ca."order")) || ':00',
       '2026-09-02 01:00:00'
FROM chapteractivity ca WHERE ca.course_id = 2 ORDER BY ca."order" LIMIT 6
ON CONFLICT (id) DO NOTHING;

INSERT INTO trailstep (id, complete, teacher_verified, grade, data, trailrun_id, trail_id,
                       activity_id, course_id, org_id, user_id, creation_date, update_date)
SELECT 9200 + row_number() OVER (ORDER BY ca."order"), true, false, '', '{}', 9002, 9002,
       ca.activity_id, 2, 1, 9002,
       '2026-09-03 01:0' || (row_number() OVER (ORDER BY ca."order")) || ':00',
       '2026-09-03 01:00:00'
FROM chapteractivity ca WHERE ca.course_id = 2 ORDER BY ca."order" LIMIT 2
ON CONFLICT (id) DO NOTHING;

-- 体检要看得见「已发布的活动」和「未发布的活动」两种，把前两个活动发布出去
UPDATE activity SET published = true
WHERE id IN (SELECT ca.activity_id FROM chapteractivity ca WHERE ca.course_id = 2 ORDER BY ca."order" LIMIT 2);

COMMIT;
