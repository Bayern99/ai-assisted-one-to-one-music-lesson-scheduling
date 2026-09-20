import { Outlet } from 'react-router-dom'
import styles from './SchedulerLayout.module.css'

export function SchedulerLayout() {
  return <div className={styles.layout}><Outlet /></div>
}
