from django.contrib import admin

from .models import Book, BookSave, BookView


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
	list_display = ('title', 'author', 'seller', 'category', 'condition', 'price', 'status', 'created_at')
	list_filter = ('status', 'category', 'condition')
	search_fields = ('title', 'author', 'course_code', 'seller__username', 'seller__first_name', 'seller__last_name')
	raw_id_fields = ('seller',)
	list_editable = ('status',)


@admin.register(BookSave)
class BookSaveAdmin(admin.ModelAdmin):
	list_display = ('book', 'user', 'created_at')
	raw_id_fields = ('book', 'user')


@admin.register(BookView)
class BookViewAdmin(admin.ModelAdmin):
	list_display = ('book', 'user', 'created_at')
	raw_id_fields = ('book', 'user')
