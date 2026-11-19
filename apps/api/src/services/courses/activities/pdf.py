from typing import Optional
from src.db.courses.courses import Course
from src.db.organizations import Organization
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from src.db.courses.chapters import Chapter
from src.db.courses.activities import (
    Activity,
    ActivityRead,
    ActivitySubTypeEnum,
    ActivityTypeEnum,
)
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.course_chapters import CourseChapter
from src.db.users import AnonymousUser, PublicUser
from src.services.courses.activities.activities import get_activity
from src.services.courses.activities.uploads.pdfs import (
    HTML_DOCUMENT_DIRECTORY,
    HTML_DOCUMENT_SUFFIX,
    upload_document,
)
from src.services.utils.upload_content import read_content
from fastapi import HTTPException, status, UploadFile, Request
from uuid import uuid4
from datetime import datetime
from src.security.rbac import check_resource_access, AccessAction


async def create_documentpdf_activity(
    request: Request,
    name: str,
    chapter_id: int,
    current_user: PublicUser | AnonymousUser,
    db_session: AsyncSession,
    pdf_file: UploadFile | None = None,
    extra_metadata: Optional[dict] = None,
):
    # get chapter_id
    statement = select(Chapter).where(Chapter.id == chapter_id)
    chapter = (await db_session.execute(statement)).scalars().first()

    if not chapter:
        raise HTTPException(
            status_code=404,
            detail="Chapter not found",
        )

    statement = select(CourseChapter).where(CourseChapter.chapter_id == chapter_id)
    coursechapter = (await db_session.execute(statement)).scalars().first()

    if not coursechapter:
        raise HTTPException(
            status_code=404,
            detail="CourseChapter not found",
        )

    # Get course_uuid for RBAC check
    statement = select(Course).where(Course.id == coursechapter.course_id)
    course = (await db_session.execute(statement)).scalars().first()

    if not course:
        raise HTTPException(
            status_code=404,
            detail="Course not found",
        )

    # RBAC check
    await check_resource_access(
        request, db_session, current_user, course.course_uuid, AccessAction.CREATE
    )

    # get org_id
    org_id = coursechapter.org_id

    # Get org_uuid
    statement = select(Organization).where(Organization.id == coursechapter.org_id)
    organization = (await db_session.execute(statement)).scalars().first()

    # create activity uuid
    activity_uuid = f"activity_{uuid4()}"

    if not pdf_file or not pdf_file.filename:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No document file provided"
        )

    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    saved_filename = await upload_document(
        pdf_file, activity_uuid, organization.org_uuid, course.course_uuid
    )

    # Create activity
    activity = Activity(
        name=name,
        activity_type=ActivityTypeEnum.TYPE_DOCUMENT,
        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DOCUMENT_PDF,
        content={
            "filename": saved_filename,
            "activity_uuid": activity_uuid,
        },
        org_id=org_id if org_id else 0,
        course_id=coursechapter.course_id,
        activity_uuid=activity_uuid,
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
        extra_metadata=extra_metadata,
    )

    # Insert Activity in DB
    db_session.add(activity)
    await db_session.commit()
    await db_session.refresh(activity)

    # Find the last activity order in the chapter
    statement = (
        select(ChapterActivity)
        .where(ChapterActivity.chapter_id == chapter_id)
        .order_by(ChapterActivity.order)  # type: ignore
    )
    chapter_activities = (await db_session.execute(statement)).scalars().all()
    last_order = chapter_activities[-1].order if chapter_activities else 0
    to_be_used_order = last_order + 1

    # Add activity to chapter
    activity_chapter = ChapterActivity(
        chapter_id=chapter_id,
        activity_id=activity.id,  # type: ignore
        course_id=coursechapter.course_id,
        org_id=coursechapter.org_id,
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
        order=to_be_used_order,
    )

    # Insert ChapterActivity link in DB
    db_session.add(activity_chapter)
    await db_session.commit()
    await db_session.refresh(activity_chapter)

    return ActivityRead.model_validate(activity)


async def update_documentpdf_activity(
    request: Request,
    activity_uuid: str,
    current_user: PublicUser | AnonymousUser,
    db_session: AsyncSession,
    name: Optional[str] = None,
    pdf_file: UploadFile | None = None,
) -> ActivityRead:
    statement = select(Activity).where(Activity.activity_uuid == activity_uuid)
    activity = (await db_session.execute(statement)).scalars().first()

    if not activity or activity.activity_type != ActivityTypeEnum.TYPE_DOCUMENT:
        raise HTTPException(status_code=404, detail="Document activity not found")

    statement = select(Course).where(Course.id == activity.course_id)
    course = (await db_session.execute(statement)).scalars().first()

    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    await check_resource_access(
        request, db_session, current_user, course.course_uuid, AccessAction.UPDATE
    )

    if name:
        activity.name = name

    if pdf_file and pdf_file.filename:
        statement = select(Organization).where(Organization.id == activity.org_id)
        organization = (await db_session.execute(statement)).scalars().first()
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        saved_filename = await upload_document(
            pdf_file, activity_uuid, organization.org_uuid, course.course_uuid
        )
        activity.content = {**(activity.content or {}), "filename": saved_filename}

    activity.update_date = str(datetime.now())
    db_session.add(activity)
    await db_session.commit()
    await db_session.refresh(activity)

    return ActivityRead.model_validate(activity)


async def get_html_document(
    request: Request,
    activity_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> bytes:
    activity = await get_activity(request, activity_uuid, current_user, db_session)
    filename = activity.content.get("filename")
    if (
        activity.activity_type != ActivityTypeEnum.TYPE_DOCUMENT
        or activity.is_locked
        or not isinstance(filename, str)
        or not filename.endswith(HTML_DOCUMENT_SUFFIX)
    ):
        raise HTTPException(status_code=404, detail="HTML document not found")

    statement = (
        select(Course.course_uuid, Organization.org_uuid)
        .join(Organization, Organization.id == Course.org_id)
        .where(Course.id == activity.course_id)
    )
    course_and_org = (await db_session.execute(statement)).first()
    if course_and_org is None:
        raise HTTPException(status_code=404, detail="HTML document not found")
    course_uuid, org_uuid = course_and_org
    return await read_content(
        directory=f"courses/{course_uuid}/activities/{activity_uuid}/{HTML_DOCUMENT_DIRECTORY}",
        type_of_dir="orgs",
        uuid=org_uuid,
        file_and_format=filename,
    )
