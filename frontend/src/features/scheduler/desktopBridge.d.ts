export {}

declare global {
  interface Window {
    piDesktop?: {
      openFile?: (kind: 'assessmentData' | 'workbook' | 'lectureCSV' | 'schedulerSource' | 'sourceData') => Promise<{
          dataBase64?: string
          location?: string
          mimeType?: string
          name?: string
          selected: boolean
          size?: number
        }>
      revealArtifact?: (artifactId: string) => Promise<unknown>
      saveArtifact?: (artifactId: string) => Promise<unknown>
    }
  }
}
