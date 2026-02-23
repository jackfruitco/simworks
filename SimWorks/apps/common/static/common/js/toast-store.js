document.addEventListener('alpine:init', () => {
  Alpine.store('toastStore', {
    create({ duration = 5000, persistent = false } = {}) {
      return {
        show: true,
        duration,
        persistent,
        init() {
          if (!this.persistent) {
            setTimeout(() => this.dismiss(), this.duration);
          }
        },
        dismiss() {
          this.show = false;
        }
      };
    }
  });
});
