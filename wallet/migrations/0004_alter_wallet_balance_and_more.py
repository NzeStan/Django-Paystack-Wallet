# Generated migration for fee_bearer field and fee configuration models

from django.db import migrations, models
import django.db.models.deletion
import djmoney.models.fields
from decimal import Decimal
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0003_remove_card_paystack_card_token_and_more'),
    ]

    operations = [
        # ==========================================
        # ADD FEE_BEARER FIELD TO TRANSACTION
        # ==========================================
        migrations.AddField(
            model_name='transaction',
            name='fee_bearer',
            field=models.CharField(
                blank=True,
                choices=[
                    ('customer', 'Customer'),
                    ('merchant', 'Merchant'),
                    ('platform', 'Platform'),
                    ('split', 'Split')
                ],
                db_index=True,
                default='platform',
                help_text='Who bears the transaction fee',
                max_length=20,
                null=True,
                verbose_name='Fee Bearer'
            ),
        ),
        
        # ==========================================
        # CREATE FEE CONFIGURATION MODEL
        # ==========================================
        migrations.CreateModel(
            name='FeeConfiguration',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('name', models.CharField(help_text='Descriptive name for this fee configuration', max_length=200, verbose_name='Configuration Name')),
                ('description', models.TextField(blank=True, null=True, verbose_name='Description')),
                ('transaction_type', models.CharField(
                    choices=[
                        ('deposit', 'Deposit'),
                        ('withdrawal', 'Withdrawal'),
                        ('transfer', 'Transfer'),
                        ('payment', 'Payment'),
                        ('refund', 'Refund'),
                        ('reversal', 'Reversal')
                    ],
                    db_index=True,
                    max_length=20,
                    verbose_name='Transaction Type'
                )),
                ('payment_channel', models.CharField(
                    blank=True,
                    choices=[
                        ('local_card', 'Local Card'),
                        ('intl_card', 'International Card'),
                        ('dva', 'Dedicated Virtual Account'),
                        ('bank_transfer', 'Bank Transfer'),
                        ('ussd', 'USSD'),
                        ('qr', 'QR Code'),
                        ('mobile_money', 'Mobile Money')
                    ],
                    db_index=True,
                    help_text='Optional: Specific payment channel for this config',
                    max_length=20,
                    null=True,
                    verbose_name='Payment Channel'
                )),
                ('fee_type', models.CharField(
                    choices=[
                        ('percentage', 'Percentage'),
                        ('flat', 'Flat'),
                        ('hybrid', 'Hybrid')
                    ],
                    default='hybrid',
                    max_length=20,
                    verbose_name='Fee Type'
                )),
                ('percentage_fee', models.DecimalField(decimal_places=2, default=0, help_text='Fee percentage (e.g., 1.5 for 1.5%)', max_digits=5, verbose_name='Percentage Fee')),
                ('flat_fee', djmoney.models.fields.MoneyField(decimal_places=2, default=0, default_currency='NGN', help_text='Fixed fee amount', max_digits=19, verbose_name='Flat Fee')),
                ('flat_fee_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('fee_cap', djmoney.models.fields.MoneyField(blank=True, decimal_places=2, default_currency='NGN', help_text='Maximum fee amount (optional)', max_digits=19, null=True, verbose_name='Fee Cap')),
                ('fee_cap_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('minimum_fee', djmoney.models.fields.MoneyField(blank=True, decimal_places=2, default_currency='NGN', help_text='Minimum fee amount (optional)', max_digits=19, null=True, verbose_name='Minimum Fee')),
                ('minimum_fee_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('waiver_threshold', djmoney.models.fields.MoneyField(blank=True, decimal_places=2, default_currency='NGN', help_text='Waive flat fee for transactions below this amount', max_digits=19, null=True, verbose_name='Waiver Threshold')),
                ('waiver_threshold_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('fee_bearer', models.CharField(
                    choices=[
                        ('customer', 'Customer'),
                        ('merchant', 'Merchant'),
                        ('platform', 'Platform'),
                        ('split', 'Split')
                    ],
                    default='platform',
                    help_text='Who bears the transaction fee',
                    max_length=20,
                    verbose_name='Fee Bearer'
                )),
                ('customer_percentage', models.DecimalField(decimal_places=2, default=50, help_text='Percentage of fee borne by customer (for split bearer)', max_digits=5, verbose_name='Customer Percentage')),
                ('merchant_percentage', models.DecimalField(decimal_places=2, default=50, help_text='Percentage of fee borne by merchant (for split bearer)', max_digits=5, verbose_name='Merchant Percentage')),
                ('is_active', models.BooleanField(default=True, verbose_name='Is active')),
                ('priority', models.IntegerField(default=0, help_text='Higher priority configs are applied first', verbose_name='Priority')),
                ('valid_from', models.DateTimeField(blank=True, help_text='Start date for this configuration', null=True, verbose_name='Valid from')),
                ('valid_until', models.DateTimeField(blank=True, help_text='End date for this configuration', null=True, verbose_name='Valid until')),
                ('metadata', models.JSONField(blank=True, default=dict, help_text='Additional configuration metadata', null=True, verbose_name='Metadata')),
                ('wallet', models.ForeignKey(
                    blank=True,
                    db_index=True,
                    help_text='Leave blank for global configuration',
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fee_configurations',
                    to='wallet.wallet',
                    verbose_name='Wallet'
                )),
            ],
            options={
                'verbose_name': 'Fee Configuration',
                'verbose_name_plural': 'Fee Configurations',
                'ordering': ['-priority', '-created_at'],
                'indexes': [
                    models.Index(fields=['transaction_type', 'is_active'], name='fee_config_type_active_idx'),
                    models.Index(fields=['wallet', 'is_active'], name='fee_config_wallet_active_idx'),
                ],
            },
        ),
        
        # ==========================================
        # CREATE FEE TIER MODEL
        # ==========================================
        migrations.CreateModel(
            name='FeeTier',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('min_amount', djmoney.models.fields.MoneyField(decimal_places=2, default=0, default_currency='NGN', help_text='Minimum transaction amount for this tier (inclusive)', max_digits=19, verbose_name='Minimum Amount')),
                ('min_amount_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('max_amount', djmoney.models.fields.MoneyField(blank=True, decimal_places=2, default_currency='NGN', help_text='Maximum transaction amount for this tier (inclusive, null = unlimited)', max_digits=19, null=True, verbose_name='Maximum Amount')),
                ('max_amount_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('fee_amount', djmoney.models.fields.MoneyField(decimal_places=2, default=0, default_currency='NGN', help_text='Fixed fee for this tier', max_digits=19, verbose_name='Fee Amount')),
                ('fee_amount_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('configuration', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='tiers',
                    to='wallet.feeconfiguration',
                    verbose_name='Fee Configuration'
                )),
            ],
            options={
                'verbose_name': 'Fee Tier',
                'verbose_name_plural': 'Fee Tiers',
                'ordering': ['min_amount'],
                'indexes': [
                    models.Index(fields=['configuration', 'min_amount'], name='tier_config_min_idx'),
                ],
            },
        ),
        
        # ==========================================
        # CREATE FEE HISTORY MODEL
        # ==========================================
        migrations.CreateModel(
            name='FeeHistory',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('calculation_method', models.CharField(help_text='settings, database, custom, etc.', max_length=50, verbose_name='Calculation Method')),
                ('original_amount', djmoney.models.fields.MoneyField(decimal_places=2, default_currency='NGN', max_digits=19, verbose_name='Original Amount')),
                ('original_amount_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('calculated_fee', djmoney.models.fields.MoneyField(decimal_places=2, default_currency='NGN', max_digits=19, verbose_name='Calculated Fee')),
                ('calculated_fee_currency', djmoney.models.fields.CurrencyField(choices=[('NGN', 'Nigerian Naira')], default='NGN', editable=False, max_length=3)),
                ('fee_bearer', models.CharField(
                    choices=[
                        ('customer', 'Customer'),
                        ('merchant', 'Merchant'),
                        ('platform', 'Platform'),
                        ('split', 'Split')
                    ],
                    max_length=20,
                    verbose_name='Fee Bearer'
                )),
                ('calculation_details', models.JSONField(default=dict, help_text='Detailed breakdown of fee calculation', verbose_name='Calculation Details')),
                ('configuration_used', models.ForeignKey(
                    blank=True,
                    help_text='Fee configuration that was used for calculation',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='fee_histories',
                    to='wallet.feeconfiguration',
                    verbose_name='Configuration Used'
                )),
                ('transaction', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='fee_history',
                    to='wallet.transaction',
                    verbose_name='Transaction'
                )),
            ],
            options={
                'verbose_name': 'Fee History',
                'verbose_name_plural': 'Fee Histories',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['transaction'], name='fee_history_txn_idx'),
                    models.Index(fields=['created_at'], name='fee_history_created_idx'),
                ],
            },
        ),
    ]