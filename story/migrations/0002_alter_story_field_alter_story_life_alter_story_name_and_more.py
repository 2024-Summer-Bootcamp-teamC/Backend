# Generated by Django 5.0.6 on 2024-07-04 06:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('story', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='story',
            name='field',
            field=models.CharField(max_length=10),
        ),
        migrations.AlterField(
            model_name='story',
            name='life',
            field=models.CharField(max_length=20),
        ),
        migrations.AlterField(
            model_name='story',
            name='name',
            field=models.CharField(max_length=10),
        ),
        migrations.AlterField(
            model_name='story',
            name='nation',
            field=models.CharField(max_length=10),
        ),
        migrations.AlterField(
            model_name='story',
            name='saying',
            field=models.CharField(max_length=255),
        ),
    ]
