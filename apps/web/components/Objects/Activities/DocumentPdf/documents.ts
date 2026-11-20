export const MAX_DOCUMENTS = 20

export type ActivityDocument = {
  filename: string
  name: string
}

export function getActivityDocuments(activity: {
  content?: { documents?: ActivityDocument[]; filename?: string } | null
  name: string
}): ActivityDocument[] {
  if (Array.isArray(activity.content?.documents)) return activity.content.documents
  const filename = activity.content?.filename
  return filename ? [{ filename, name: activity.name }] : []
}
