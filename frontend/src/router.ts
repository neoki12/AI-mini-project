import { createRouter, createWebHashHistory } from 'vue-router'

import AdminView from './views/AdminView.vue'
import ReviewDetail from './views/ReviewDetail.vue'
import ReviewHistory from './views/ReviewHistory.vue'
import ReviewNew from './views/ReviewNew.vue'

// 해시 라우팅 — FastAPI가 dist/를 정적 파일로 서빙할 때 /reviews/rv-... 같은 깊은 링크를
// 새로고침해도 404가 나지 않도록 서버 쪽 fallback 설정이 필요 없게 한다.
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'review-new', component: ReviewNew },
    { path: '/reviews', name: 'review-history', component: ReviewHistory },
    { path: '/reviews/:id', name: 'review-detail', component: ReviewDetail, props: true },
    { path: '/admin', name: 'admin', component: AdminView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
